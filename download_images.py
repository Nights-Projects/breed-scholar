#!/usr/bin/env python3
"""Download images from Wikimedia Commons URLs stored in the database
and generate 200x200 thumbnails."""

import argparse
import os
import sqlite3
import time
from pathlib import Path

import requests
from PIL import Image

try:
    from PIL.Image import Resampling
    LANCZOS = Resampling.LANCZOS
except ImportError:
    try:
        LANCZOS = Image.LANCZOS
    except AttributeError:
        LANCZOS = 3
from io import BytesIO

BASE_DIR = Path(os.environ.get('BASE_DIR', Path(__file__).resolve().parent))
DB_PATH = BASE_DIR / 'dog_breeds.db'
THUMBS_DIR = BASE_DIR / 'static' / 'thumbs'
FULL_DIR = BASE_DIR / 'static' / 'full'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; BreedScholar/1.0; +https://github.com/WickedYoda/breed-scholar)'
}


def get_wikimedia_image_url(breed_name):
    """Query Wikimedia Commons API for actual image URL."""
    filenames = [
        f'{breed_name.replace(" ", "_")}.jpg',
        f'{breed_name.replace(" ", "_")}.jpeg',
        f'{breed_name.replace(" ", "_")}.png',
    ]
    
    for filename in filenames:
        api_url = 'https://commons.wikimedia.org/w/api.php'
        params = {
            'action': 'query',
            'titles': f'File:{filename}',
            'prop': 'imageinfo',
            'iiprop': 'url',
            'format': 'json'
        }
        
        try:
            resp = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            pages = data.get('query', {}).get('pages', {})
            for page_data in pages.values():
                if 'imageinfo' in page_data:
                    return page_data['imageinfo'][0]['url']
        except requests.RequestException:
            continue
    
    # Fallback: search for breed image
    try:
        search_url = 'https://commons.wikimedia.org/w/api.php'
        params = {
            'action': 'query',
            'list': 'search',
            'srsearch': f'{breed_name} dog',
            'srnamespace': 6,
            'srlimit': 1,
            'format': 'json'
        }
        resp = requests.get(search_url, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        results = data.get('query', {}).get('search', [])
        if results:
            filename = results[0]['title'].replace('File:', '')
            api_url = 'https://commons.wikimedia.org/w/api.php'
            params = {
                'action': 'query',
                'titles': f'File:{filename}',
                'prop': 'imageinfo',
                'iiprop': 'url',
                'format': 'json'
            }
            resp = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            pages = data.get('query', {}).get('pages', {})
            for page_data in pages.values():
                if 'imageinfo' in page_data:
                    return page_data['imageinfo'][0]['url']
    except requests.RequestException as e:
        print(f'  [!] Wikimedia search fallback error: {e}')
    except (ValueError, KeyError) as e:
        print(f'  [!] Wikimedia response parse error: {e}')
    
    return None


def download_and_thumbnail(image_url, breed_id):
    """Download image and create 200x200 thumbnail."""
    try:
        resp = requests.get(image_url, headers=HEADERS, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        
        img = Image.open(BytesIO(resp.content))
        
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        full_path = FULL_DIR / f'{breed_id}.jpg'
        img.save(full_path, 'JPEG', quality=85)
        
        thumb = img.copy()
        thumb.thumbnail((200, 200), LANCZOS)
        
        thumb_square = Image.new('RGB', (200, 200), (30, 30, 40))
        offset = ((200 - thumb.width) // 2, (200 - thumb.height) // 2)
        thumb_square.paste(thumb, offset)
        
        thumb_path = THUMBS_DIR / f'{breed_id}.jpg'
        thumb_square.save(thumb_path, 'JPEG', quality=80)
        
        return True
    except (requests.RequestException, OSError, ValueError) as e:
        print(f'  [!] Failed: {e}')
        return False


def main():
    parser = argparse.ArgumentParser(description='Download and thumbnail breed images')
    parser.add_argument('--limit', type=int, default=0, help='Limit breeds to process')
    parser.add_argument('--skip-existing', action='store_true', help='Skip breeds that already have thumbnails')
    parser.add_argument('--force', action='store_true', help='Force re-download even if thumbnail exists')
    args = parser.parse_args()
    
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute('SELECT id, name, image_url FROM breeds WHERE image_url IS NOT NULL AND image_url != ""')
    breeds = cur.fetchall()
    conn.close()
    
    if args.limit > 0:
        breeds = breeds[:args.limit]
    
    print(f'[*] Found {len(breeds)} breeds with image URLs')
    print(f'[*] Thumbs dir: {THUMBS_DIR}')
    print(f'[*] Full dir: {FULL_DIR}')
    
    downloaded = 0
    skipped = 0
    failed = 0
    
    for i, (breed_id, breed_name, image_url) in enumerate(breeds, 1):
        thumb_path = THUMBS_DIR / f'{breed_id}.jpg'
        
        if not args.force and thumb_path.exists() and args.skip_existing:
            skipped += 1
            continue
        
        print(f'  [{i}/{len(breeds)}] {breed_name}')
        
        actual_url = get_wikimedia_image_url(breed_name)
        if not actual_url:
            print(f'    [!] No image found for {breed_name}')
            failed += 1
            continue
        
        if download_and_thumbnail(actual_url, breed_id):
            downloaded += 1
            print('    [+] Downloaded')
        else:
            failed += 1
        
        time.sleep(0.5)
    
    print('\n[*] Summary:')
    print(f'    Downloaded: {downloaded}')
    print(f'    Skipped:    {skipped}')
    print(f'    Failed:     {failed}')
    print(f'    Total:      {len(breeds)}')


if __name__ == '__main__':
    main()
