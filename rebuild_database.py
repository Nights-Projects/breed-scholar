#!/usr/bin/env python3
"""
Rebuild dog_breeds.db from scratch by crawling AKC and other sources.
Usage: python rebuild_database.py [--depth N] [--skip-images]
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path('/root/breed-scholar')
DB_PATH = BASE_DIR / 'dog_breeds.db'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; BreedScholar/1.0; +https://github.com/WickedYoda/breed-scholar)'
}
AKC_BASE = 'https://www.akc.org/dog-breeds/'


def fetch_page(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [!] Failed to fetch {url}: {e}")
                return None
    return None


def extract_akc_breed_links(html, base_url):
    """Extract breed page URLs from AKC listing pages."""
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/dog-breeds/' in href:
            full_url = urljoin(base_url, href)
            links.add(full_url)
    return links


def parse_akc_breed_page(html, url):
    """Parse an AKC breed page for name, group, rank, description."""
    soup = BeautifulSoup(html, 'html.parser')
    
    # Title / name
    name = ''
    h1 = soup.find('h1')
    if h1:
        name = h1.get_text(strip=True)
    if not name:
        title = soup.find('title')
        if title:
            name = title.get_text(strip=True).split('|')[0].strip()
    
    if not name:
        return None
    
    # Extract text content for facts/tips
    content_div = soup.find('div', class_=re.compile('breed-content|content|description'))
    if not content_div:
        content_div = soup.find('article') or soup.find('main') or soup
    
    paragraphs = [p.get_text(strip=True) for p in content_div.find_all('p') if p.get_text(strip=True)]
    fact = ' '.join(paragraphs[:3]) if paragraphs else f'{name} is recognized by the AKC.'
    
    # Try to find group
    group = ''
    group_match = re.search(r'Group:\s*([^<\n]+)', html)
    if group_match:
        group = group_match.group(1).strip()
    
    # Try to find rank from page
    rank = None
    rank_match = re.search(r'Ranked\s+#?(\d+)|#(\d+)\s+most popular', html, re.IGNORECASE)
    if rank_match:
        rank = int(rank_match.group(1) or rank_match.group(2))
    
    return {
        'name': name,
        'group': group,
        'rank': rank,
        'country': '',
        'size': '',
        'fci_group': '',
        'fact': fact[:500] if fact else '',
        'tips': f'Study {name}\'s distinctive features: coat type, build, and temperament.',
        'image_url': f'https://commons.wikimedia.org/wiki/Special:FilePath/{name.replace(" ", "_")}?width=400',
        'registry': 'akc',
        'source_url': url
    }


def crawl_akc(max_depth=10):
    """Crawl AKC breed pages up to max_depth levels deep."""
    print(f"[*] Crawling AKC (depth={max_depth})...")
    
    visited = set()
    to_visit = [AKC_BASE]
    breed_data = {}
    
    for depth in range(max_depth):
        if not to_visit:
            break
        
        current_urls = to_visit
        to_visit = []
        print(f"  Depth {depth + 1}: {len(current_urls)} pages")
        
        for url in current_urls:
            if url in visited:
                continue
            visited.add(url)
            
            html = fetch_page(url)
            if not html:
                continue
            
            # Check if this is a breed page
            if '/dog-breeds/' in url and not url.endswith('/dog-breeds/'):
                breed_info = parse_akc_breed_page(html, url)
                if breed_info:
                    breed_data[breed_info['name']] = breed_info
                    print(f"    [+] Found breed: {breed_info['name']}")
            
            # Extract links for next depth
            if depth < max_depth - 1:
                new_links = extract_akc_breed_links(html, url)
                for link in new_links:
                    if link not in visited:
                        to_visit.append(link)
            
            time.sleep(0.5)  # Be polite
    
    print(f"[*] Found {len(breed_data)} AKC breeds")
    return breed_data


def init_database():
    """Create or recreate the database schema."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS registries (
            id INTEGER PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS breeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_name TEXT,
            rank INTEGER,
            country TEXT,
            size TEXT,
            fci_group TEXT,
            fact TEXT,
            tips TEXT,
            image_url TEXT,
            source_url TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS breed_registries (
            breed_id INTEGER NOT NULL,
            registry_id INTEGER NOT NULL,
            PRIMARY KEY (breed_id, registry_id),
            FOREIGN KEY (breed_id) REFERENCES breeds(id),
            FOREIGN KEY (registry_id) REFERENCES registries(id)
        )
    ''')
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_breeds_name ON breeds(name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_breeds_rank ON breeds(rank)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_breeds_country ON breeds(country)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_breeds_group ON breeds(group_name)')
    
    # Insert registries
    cursor.execute("INSERT OR IGNORE INTO registries (id, code, name) VALUES (1, 'akc', 'American Kennel Club')")
    cursor.execute("INSERT OR IGNORE INTO registries (id, code, name) VALUES (2, 'fci', 'Fédération Cynologique Internationale')")
    cursor.execute("INSERT OR IGNORE INTO registries (id, code, name) VALUES (3, 'non', 'Non-Recognized / Other')")
    
    conn.commit()
    conn.close()
    print("[*] Database initialized")


def populate_database(breed_data):
    """Insert breed data into the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    registry_map = {'akc': 1, 'fci': 2, 'non': 3}
    
    for breed in breed_data.values():
        cursor.execute('''
            INSERT OR REPLACE INTO breeds 
            (name, group_name, rank, country, size, fci_group, fact, tips, image_url, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            breed['name'],
            breed.get('group', ''),
            breed.get('rank'),
            breed.get('country', ''),
            breed.get('size', ''),
            breed.get('fci_group', ''),
            breed.get('fact', ''),
            breed.get('tips', ''),
            breed.get('image_url', ''),
            breed.get('source_url', '')
        ))
        
        breed_id = cursor.lastrowid
        reg_id = registry_map.get(breed.get('registry', 'non'))
        if reg_id:
            cursor.execute('INSERT OR IGNORE INTO breed_registries (breed_id, registry_id) VALUES (?, ?)',
                          (breed_id, reg_id))
    
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM breeds')
    total = cursor.fetchone()[0]
    conn.close()
    
    print(f"[*] Database populated: {total} breeds")
    return total


def main():
    parser = argparse.ArgumentParser(description='Rebuild dog breed database from AKC and other sources')
    parser.add_argument('--depth', type=int, default=10, help='Crawl depth (default: 10)')
    parser.add_argument('--skip-crawl', action='store_true', help='Skip crawling, use existing JSON')
    parser.add_argument('--json-input', type=str, help='Load breed data from JSON file instead of crawling')
    args = parser.parse_args()
    
    # Initialize database
    init_database()
    
    if args.json_input:
        # Load from JSON file
        with open(args.json_input, 'r') as f:
            breed_data = json.load(f)
        print(f"[*] Loaded {len(breed_data)} breeds from {args.json_input}")
    elif not args.skip_crawl:
        # Crawl AKC
        breed_data = crawl_akc(max_depth=args.depth)
        
        # Save raw data
        with open(BASE_DIR / 'akc_crawl_results.json', 'w') as f:
            json.dump(breed_data, f, indent=2, ensure_ascii=False)
        print("[*] Saved crawl results to akc_crawl_results.json")
    else:
        print("[!] No data source specified. Use --json-input or remove --skip-crawl")
        return
    
    # Populate database
    total = populate_database(breed_data)
    print(f"[✓] Database rebuilt with {total} breeds")
    print(f"[✓] Database location: {DB_PATH}")


if __name__ == '__main__':
    main()
