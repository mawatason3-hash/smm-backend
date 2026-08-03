import os
import asyncio
import httpx
from dotenv import load_dotenv


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


async def main():
    key = os.environ.get('WIZSMM_API_KEY')
    if not key:
        print('WIZSMM_API_KEY not set')
        return

    url = os.environ.get('WIZSMM_API_URL', 'https://wizsmm.com/api/v2')
    data = {'key': key, 'action': 'services'}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(url, data=data)
            r.raise_for_status()
            resp = r.json()
            if isinstance(resp, list):
                print(f'Retrieved {len(resp)} services')
                for item in resp[:5]:
                    # print minimal info
                    print('-', item.get('name') or item.get('service') or item.get('services') or item.get('Category'))
            elif isinstance(resp, dict):
                print('Response keys:', ', '.join(resp.keys()))
            else:
                print('Unexpected response type')
        except Exception as e:
            print('Request failed:', e)


if __name__ == '__main__':
    asyncio.run(main())
