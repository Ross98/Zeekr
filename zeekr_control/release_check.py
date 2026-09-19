"""Read-only release gate. Also runnable standalone by systemd outside releases.

Run as the service account, never infer readability from a root-only inspection.
No session, vehicle gateway, notification or database access.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import sys
from xml.etree import ElementTree


class ReleaseCheckError(ValueError):
    pass


def check_release(root, require_image=False, service_user=None):
    if service_user:
        try:
            expected = pwd.getpwnam(service_user).pw_uid
        except KeyError:
            raise ReleaseCheckError('指定服务用户不存在。') from None
        if os.geteuid() != expected:
            raise ReleaseCheckError('必须以指定服务用户执行检查，不能用管理员权限替代。')
    package = Path(root)/'zeekr_control'
    try:
        config = json.loads((package/'vehicle_profiles.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        if not require_image:
            return {'configured_images':0, 'artwork_checked':False}
        raise ReleaseCheckError('车型配置缺失，拒绝丢失已配置的车型图片。') from None
    except (OSError, UnicodeError, ValueError):
        raise ReleaseCheckError('车型配置无法读取或格式无效；请检查服务用户的属主、组及权限。') from None
    if not isinstance(config, dict) or not isinstance(config.get('vehicles', {}), dict):
        raise ReleaseCheckError('车型配置结构无效。')
    profiles = list(config.get('vehicles', {}).values())
    if config.get('single_vehicle') is not None:
        profiles.append(config['single_vehicle'])
    images = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ReleaseCheckError('车型配置条目无效。')
        image = profile.get('image', '')
        if image not in ('', '/car.svg'):
            raise ReleaseCheckError('车型图片路径无效；不能依赖运行时静默回退。')
        images += image == '/car.svg'
    if not images:
        if require_image:
            raise ReleaseCheckError('没有有效车型图片配置，拒绝发布。')
        return {'configured_images':0, 'artwork_checked':False}
    try:
        png = (package/'static/car-001.png').read_bytes()
        svg = ElementTree.fromstring((package/'static/car.svg').read_bytes())
        wrappers = list(svg.iter('{http://www.w3.org/2000/svg}image'))
        if len(wrappers) != 1 or not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('invalid artwork')
        href = wrappers[0].get('href', '')
        prefix = 'data:image/png;base64,'
        if not href.startswith(prefix) or base64.b64decode(href[len(prefix):], validate=True) != png:
            raise ValueError('artwork mismatch')
    except (OSError, ValueError, ElementTree.ParseError):
        raise ReleaseCheckError('车型图片不可读取、损坏，或概览与详情图片不一致。') from None
    return {'configured_images':images, 'artwork_checked':True}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check profile and artwork as the actual service account.')
    parser.add_argument('root', type=Path)
    parser.add_argument('--require-image', action='store_true')
    parser.add_argument('--service-user')
    args = parser.parse_args(argv)
    try:
        result = check_release(args.root, args.require_image, args.service_user)
    except ReleaseCheckError as exc:
        print('RELEASE_CHECK_FAILED: '+str(exc), file=sys.stderr)
        return 1
    print('RELEASE_CHECK_PASS: '+json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
