"""Convert the frozen plain-text report into conservative WeCom markdown."""
import re


def markdown_for(message):
    lines = message.splitlines()
    result = []
    for index, line in enumerate(lines):
        if index == 0 and line:
            line = '## ' + line
        elif line.startswith('【') and line.endswith('】'):
            line = '**' + line[1:-1] + '**'
        elif line == '状态来自车辆云端缓存，时间可能延迟。':
            line = '<font color="comment">' + line + '</font>'
        line = re.sub(r'变化 -([0-9]+(?:\.[0-9]+)?) 个百分点', r'下降 \1 个百分点', line)
        line = re.sub(r'变化 -([0-9]+(?:\.[0-9]+)?) 公里', r'减少 \1 公里', line)
        result.append(line)
    return '\n'.join(result)
