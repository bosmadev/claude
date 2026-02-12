#!/usr/bin/env python3
"""Test X API access via curl_cffi + XClientTransaction"""
import json, asyncio, re, sys
from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup
from x_client_transaction import ClientTransaction
from pathlib import Path

BEARER = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

def get_data_dir():
    return Path(__file__).parent.parent / "data"

async def init_session():
    """Initialize curl_cffi session with cookies + transaction ID generator"""
    cookies_path = get_data_dir() / "cookies.json"
    with open(cookies_path) as f:
        cd = json.load(f)

    s = AsyncSession(impersonate='chrome131')
    s.cookies.set('ct0', cd['ct0'], domain='.x.com')
    s.cookies.set('auth_token', cd['auth_token'], domain='.x.com')

    # Fetch homepage (sets __cf_bm and other Cloudflare cookies)
    home_r = await s.get('https://x.com', headers={'user-agent': UA})
    if home_r.status_code != 200:
        print(f"ERROR: Homepage returned {home_r.status_code}")
        return None, None, None

    home_soup = BeautifulSoup(home_r.text, 'html.parser')

    # Find ondemand.s JS bundle
    ON_DEMAND_RE = re.compile(r"""['|"]{1}ondemand\.s['|"]{1}:\s*['|"]{1}([\w]*)['|"]{1}""")
    hashes = ON_DEMAND_RE.findall(home_r.text)
    if not hashes:
        print("ERROR: Could not find ondemand.s hash")
        return None, None, None

    ondemand_url = f'https://abs.twimg.com/responsive-web/client-web/ondemand.s.{hashes[0]}a.js'
    ondemand_r = await s.get(ondemand_url, headers={'user-agent': UA})

    ct = ClientTransaction(home_soup, ondemand_r.text)

    return s, ct, cd['ct0']


def build_headers(ct, csrf, method, path):
    """Build full X API headers with transaction ID"""
    tx_id = ct.generate_transaction_id(method=method, path=path)
    return {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'authorization': BEARER,
        'referer': 'https://x.com/',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': UA,
        'x-client-transaction-id': tx_id,
        'x-csrf-token': csrf,
        'x-twitter-active-user': 'yes',
        'x-twitter-auth-type': 'OAuth2Session',
        'x-twitter-client-language': 'en',
    }


async def test_auth():
    """Test authentication against X API"""
    print("=== X API Auth Test (curl_cffi + XClientTransaction) ===\n")

    print("1. Initializing session...")
    s, ct, csrf = await init_session()
    if not s:
        return False
    print("   OK - session initialized, cookies set\n")

    # Print bearer token to verify no shell escaping issues
    print(f"2. Bearer token check: ...{BEARER[-20:]}")
    print(f"   Contains %3D: {'%3D' in BEARER}")
    print(f"   Contains %%: {'%%' in BEARER}\n")

    # Test 1: account/settings (v1.1 REST)
    print("3. Testing /i/api/1.1/account/settings.json...")
    path1 = '/i/api/1.1/account/settings.json'
    h1 = build_headers(ct, csrf, 'GET', path1)
    r1 = await s.get(f'https://x.com{path1}', headers=h1)
    print(f"   Status: {r1.status_code}, Body length: {len(r1.text)}")
    if r1.status_code == 200:
        print(f"   Screen name: {r1.json().get('screen_name')}")
    else:
        print(f"   Response headers: {dict(list(r1.headers.items())[:5])}")

    # Test 2: Viewer GraphQL
    print("\n4. Testing /i/api/graphql/*/Viewer (GraphQL)...")
    # Use a known query ID for Viewer
    path2 = '/i/api/graphql/pjFnHGVqCjTcZol0xcBJjw/Viewer'
    params2 = '?variables=%7B%22withCommunitiesMemberships%22%3Atrue%7D&features=%7B%22rweb_tipjar_consumption_enabled%22%3Atrue%7D&fieldToggles=%7B%22isDelegate%22%3Afalse%7D'
    h2 = build_headers(ct, csrf, 'GET', path2)
    r2 = await s.get(f'https://x.com{path2}{params2}', headers=h2)
    print(f"   Status: {r2.status_code}, Body length: {len(r2.text)}")
    if r2.status_code == 200:
        data = r2.json()
        viewer = data.get('data', {}).get('viewer', {}).get('user_results', {}).get('result', {})
        legacy = viewer.get('legacy', {})
        print(f"   Viewer: @{legacy.get('screen_name', '?')}")
    else:
        print(f"   Body: {r2.text[:200]}")

    # Test 3: Try without transaction ID to confirm it's needed
    print("\n5. Control test (no transaction ID)...")
    h3 = build_headers(ct, csrf, 'GET', path1)
    del h3['x-client-transaction-id']
    r3 = await s.get(f'https://x.com{path1}', headers=h3)
    print(f"   Status: {r3.status_code} (expected 404 without tx-id)")

    await s.close()
    return r1.status_code == 200 or r2.status_code == 200


if __name__ == '__main__':
    ok = asyncio.run(test_auth())
    print(f"\n{'=== SUCCESS ===' if ok else '=== FAILED ==='}")
    sys.exit(0 if ok else 1)
