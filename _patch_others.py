# Patch 404.html, injury.html, plan.html to hide /upload links
import re

def patch_file(filepath, old_bytes, new_bytes):
    with open(filepath, 'rb') as f:
        raw = f.read()
    if old_bytes in raw:
        raw = raw.replace(old_bytes, new_bytes)
        with open(filepath, 'wb') as f:
            f.write(raw)
        print(f'OK: {filepath}')
        return True
    else:
        print(f'NOT FOUND in {filepath}: {old_bytes[:50]}')
        return False

# 404.html: hide /upload link
with open('C:/swim/frontend/404.html', 'rb') as f:
    raw404 = f.read()
idx = raw404.find(b'href="/upload"')
if idx != -1:
    # Find the full <a> tag
    tag_start = raw404.rfind(b'<a ', 0, idx)
    tag_end = raw404.find(b'</a>', idx) + 4
    old_tag = raw404[tag_start:tag_end]
    # Insert display:none into class or add style
    new_tag = old_tag.replace(b'href="/upload"', b'href="/upload" style="display:none"')
    raw404 = raw404[:tag_start] + new_tag + raw404[tag_end:]
    with open('C:/swim/frontend/404.html', 'wb') as f:
        f.write(raw404)
    print('404.html: upload link hidden')

# injury.html: hide /upload link
with open('C:/swim/frontend/injury.html', 'rb') as f:
    raw_inj = f.read()
idx = raw_inj.find(b'href="/upload"')
if idx != -1:
    tag_start = raw_inj.rfind(b'<a ', 0, idx)
    tag_end = raw_inj.find(b'</a>', idx) + 4
    old_tag = raw_inj[tag_start:tag_end]
    new_tag = old_tag.replace(b'href="/upload"', b'href="/upload" style="display:none"')
    raw_inj = raw_inj[:tag_start] + new_tag + raw_inj[tag_end:]
    with open('C:/swim/frontend/injury.html', 'wb') as f:
        f.write(raw_inj)
    print('injury.html: upload link hidden')

# plan.html: hide /upload link (inside JS template literal)
with open('C:/swim/frontend/plan.html', 'rb') as f:
    raw_plan = f.read()
idx = raw_plan.find(b'href="/upload"')
if idx != -1:
    tag_start = raw_plan.rfind(b'<a ', 0, idx)
    tag_end = raw_plan.find(b'</a>', idx) + 4
    old_tag = raw_plan[tag_start:tag_end]
    new_tag = old_tag.replace(b'href="/upload"', b'href="/upload" style="display:none"')
    raw_plan = raw_plan[:tag_start] + new_tag + raw_plan[tag_end:]
    with open('C:/swim/frontend/plan.html', 'wb') as f:
        f.write(raw_plan)
    print('plan.html: upload link hidden')
