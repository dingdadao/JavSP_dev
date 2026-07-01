#!/usr/bin/env python3
"""
JavSP API 服务器启动脚本

用法:
    python api_server.py              # 使用默认配置启动
    python api_server.py --port 8080  # 指定端口
    python api_server.py --host 127.0.0.1 --port 5000  # 指定主机和端口
"""

import argparse
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from javsp.api import run_api_server
import logging


def main():
    parser = argparse.ArgumentParser(
        description='JavSP API 服务器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                           # 默认启动 (0.0.0.0:5000)
  %(prog)s --port 8080               # 使用端口 8080
  %(prog)s --host 127.0.0.1          # 仅本地访问
  %(prog)s --debug                   # 调试模式
        """
    )
    
    parser.add_argument(
        '--host',
        default='0.0.0.0',
        help='服务器主机地址 (默认: 0.0.0.0)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='服务器端口 (默认: 5000)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试模式'
    )
    
    args = parser.parse_args()
    
    # 配置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    print(f"""
╔══════════════════════════════════════════════════════════╗
║                    JavSP API 服务器                      ║
╠══════════════════════════════════════════════════════════╣
║  地址: http://{args.host}:{args.port:<21}              ║
║  调试模式: {'开启':<36}              ║
╠══════════════════════════════════════════════════════════╣
║  接口文档: http://{args.host}:{args.port}/docs           ║
╚══════════════════════════════════════════════════════════╝
""")
    
    try:
        run_api_server(
            host=args.host,
            port=args.port,
            debug=args.debug
        )
    except KeyboardInterrupt:
        print("\n服务器已停止")
        sys.exit(0)


if __name__ == '__main__':
    main()
