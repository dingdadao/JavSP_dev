"""JavSP Web 服务器启动入口"""

import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(description='JavSP Web 管理界面')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5001, help='监听端口 (默认: 5001)')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    from javsp.webapp.app import run_web_server
    run_web_server(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
