# -*- coding: utf-8 -*-
"""Patch dashboard.html to hide analysis sections"""

with open('C:/swim/frontend/dashboard.html', 'rb') as f:
    raw = f.read()

# 1. back-btn: ← 분석하러 가기 → ← 홈으로
old_btn = '← 분석하러 가기</a>'.encode('utf-8')
new_btn = '← 홈으로</a>'.encode('utf-8')
raw = raw.replace(old_btn, new_btn)

# 2. dash-title: 분析 현황 대시보드 → 내 현황
old_title = '>분析 현황 대시보드<'.encode('utf-8')
new_title = '>내 현황<'.encode('utf-8')
raw = raw.replace(old_title, new_title)

# 3. Hide summary-cards
old3 = '<!-- 숫자 카드 -->\r\n    <div class="summary-cards">'.encode('utf-8')
new3 = '<!-- 숫자 카드 -->\r\n    <div class="summary-cards" style="display:none">'.encode('utf-8')
raw = raw.replace(old3, new3)

# 4. Hide charts-grid (already done by earlier script, but ensure)
old4 = '<!-- 차트 2×2 -->\r\n    <div class="charts-grid">'.encode('utf-8')
new4 = '<!-- 차트 2×2 -->\r\n    <div class="charts-grid" style="display:none">'.encode('utf-8')
raw = raw.replace(old4, new4)

# 5. Hide table-card
old5 = '<div class="table-card">'.encode('utf-8')
new5 = '<div class="table-card" style="display:none">'.encode('utf-8')
raw = raw.replace(old5, new5)

# 6. Hide history-section
old6 = '<div class="history-section">'.encode('utf-8')
new6 = '<div class="history-section" style="display:none">'.encode('utf-8')
raw = raw.replace(old6, new6)

# 7. Hide weekly-card (already done, but ensure)
old7 = '<!-- 주간 목표 -->\r\n    <div class="weekly-card">'.encode('utf-8')
new7 = '<!-- 주간 목표 -->\r\n    <div class="weekly-card" style="display:none">'.encode('utf-8')
raw = raw.replace(old7, new7)

# 8. Add "준비 중" notice after mini-badge-row closing div
notice_html = b'\r\n\r\n    <!-- AI \xeb\xb6\x84\xec\x84\x9d \xea\xb8\xb0\xeb\x8a\xa5 \xec\xa4\x80\xeb\xb9\x84 \xec\xa4\x91 \xec\x95\x88\xeb\x82\xb4 -->\r\n    <div id="analysis-coming-soon" style="background:var(--surface);border:0.5px solid var(--border);border-radius:10px;padding:32px 20px;text-align:center;margin-bottom:20px;">\r\n      <div style="font-size:32px;margin-bottom:12px;">&#x1F6A7;</div>\r\n      <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:8px;">AI \xeb\xb6\x84\xec\x84\x9d \xea\xb8\xb0\xeb\x8a\xa5 \xec\xa4\x80\xeb\xb9\x84 \xec\xa4\x91</div>\r\n      <div style="font-size:13px;color:var(--muted);line-height:1.7;">\xec\x88\x98\xec\x98\x81 \xec\x98\x81\xec\x83\x81 \xeb\xb6\x84\xec\x84\x9d \xeb\xb0\x8f \xec\x9e\x90\xec\x84\xb8 \xeb\xb6\x84\xec\x84\x9d \xea\xb8\xb0\xeb\x8a\xa5\xec\x9d\xb4 \xea\xb3\xa7 \xec\xa0\x9c\xea\xb3\xb5\xeb\x90\xa0 \xec\x98\x88\xec\xa0\x95\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4.<br>\xec\x97\x85\xeb\x8d\xb0\xec\x9d\xb4\xed\x8a\xb8 \xec\x86\x8c\xec\x8b\x9d\xec\x9d\x80 \xeb\xa6\xb4\xeb\xa6\xac\xec\xa6\x88 \xeb\x85\xb8\xed\x8a\xb8\xec\x97\x90\xec\x84\x9c \xed\x99\x95\xec\x9d\xb8\xed\x95\x98\xec\x84\xb8\xec\x9a\x94.</div>\r\n      <a href="/changelog" style="display:inline-block;margin-top:16px;padding:8px 20px;background:var(--blue);color:#fff;text-decoration:none;border-radius:8px;font-size:13px;font-weight:600;">\xeb\xa6\xb4\xeb\xa6\xac\xec\xa6\x88 \xeb\x85\xb8\xed\x8a\xb8 \xeb\xb3\xb4\xea\xb8\xb0</a>\r\n    </div>'

# Find mini-badge-row closing </div> then insert notice
idx = raw.find(b'class="mini-badge-row"')
if idx != -1:
    # Find the closing </div> of this element
    close_div = raw.find(b'\r\n    </div>', idx)
    if close_div != -1:
        insert_at = close_div + len(b'\r\n    </div>')
        raw = raw[:insert_at] + notice_html + raw[insert_at:]
        print('Notice inserted after mini-badge-row')
    else:
        print('Could not find mini-badge-row closing div')
else:
    print('mini-badge-row not found')

with open('C:/swim/frontend/dashboard.html', 'wb') as f:
    f.write(raw)

print('Done. Verifying...')
# Verify changes
content = raw.decode('utf-8', errors='replace')
checks = [
    ('홈으로', 'topbar back-btn'),
    ('내 현황', 'dash-title'),
    ('summary-cards" style="display:none"', 'summary-cards hidden'),
    ('charts-grid" style="display:none"', 'charts-grid hidden'),
    ('table-card" style="display:none"', 'table-card hidden'),
    ('history-section" style="display:none"', 'history-section hidden'),
    ('weekly-card" style="display:none"', 'weekly-card hidden'),
    ('analysis-coming-soon', 'coming-soon notice'),
]
for check, label in checks:
    found = check in content
    print(f'  {"OK" if found else "MISSING"}: {label}')
