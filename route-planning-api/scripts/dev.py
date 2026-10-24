"""Start the API; run the Vite frontend separately from the repository root."""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    uvicorn.run('service.main:app', host=args.host, port=args.port)


if __name__ == '__main__':
    main()
