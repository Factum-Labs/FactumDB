"""Upload a results archive to a controller-signed URL without guest AWS credentials."""
import argparse
import http.client
from pathlib import Path
import time
from urllib.parse import urlsplit
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', nargs='?')
    parser.add_argument('--bucket')
    parser.add_argument('--directory', type=Path, default=Path('results'))
    options = parser.parse_args()
    target = options.directory.with_suffix('.zip')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in options.directory.rglob('*'):
            if path.is_file():
                archive.write(path, str(path.relative_to(options.directory)))
    if options.bucket:
        import boto3
        boto3.client('s3', region_name='ap-southeast-2').upload_file(str(target), options.bucket, 'results/guest.zip')
        return
    if not options.url:
        parser.error('Provide --bucket or a signed URL')
    url = urlsplit(options.url)
    if url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.amazonaws.com'):
        raise ValueError('Expected an HTTPS S3 URL')
    for attempt in range(3):
        connection = http.client.HTTPSConnection(url.hostname, timeout=60)
        try:
            with target.open('rb') as body:
                connection.request('PUT', url.path + '?' + url.query, body=body,
                                   headers={'Content-Length': str(target.stat().st_size)})
                response = connection.getresponse()
                response.read()
                if 200 <= response.status < 300:
                    return
                raise RuntimeError(f'Result upload returned HTTP {response.status}')
        except (OSError, RuntimeError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        finally:
            connection.close()


if __name__ == '__main__':
    main()
