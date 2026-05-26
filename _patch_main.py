# Patch api/main.py to add admin-only check for analysis routes
with open('C:/swim/api/main.py', 'rb') as f:
    raw = f.read()

# Replace meta route (CRLF line endings)
old_meta = b'@app.get("/meta")\r\ndef serve_meta(request: Request):\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    return _serve("meta.html")'
new_meta = b'@app.get("/meta")\r\ndef serve_meta(request: Request):  # admin-only\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    if not _is_admin(request):\r\n        return RedirectResponse(url="/landing")\r\n    return _serve("meta.html")'
print('meta found:', old_meta in raw)
raw = raw.replace(old_meta, new_meta)

# Replace upload route
old_upload = b'@app.get("/upload")\r\ndef serve_upload(request: Request):\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    return _serve("upload.html")'
new_upload = b'@app.get("/upload")\r\ndef serve_upload(request: Request):  # admin-only\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    if not _is_admin(request):\r\n        return RedirectResponse(url="/landing")\r\n    return _serve("upload.html")'
print('upload found:', old_upload in raw)
raw = raw.replace(old_upload, new_upload)

# Replace viewer route
old_viewer = b'@app.get("/viewer")\r\ndef serve_viewer(request: Request):\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    return _serve("viewer.html")'
new_viewer = b'@app.get("/viewer")\r\ndef serve_viewer(request: Request):  # admin-only\r\n    redir = _auth_redirect(request)\r\n    if redir: return redir\r\n    if not _is_admin(request):\r\n        return RedirectResponse(url="/landing")\r\n    return _serve("viewer.html")'
print('viewer found:', old_viewer in raw)
raw = raw.replace(old_viewer, new_viewer)

with open('C:/swim/api/main.py', 'wb') as f:
    f.write(raw)
print('main.py patched')

# Verify
with open('C:/swim/api/main.py', 'rb') as f:
    check = f.read()
print('meta _is_admin:', b'_is_admin' in check)
print('upload _is_admin:', check.count(b'_is_admin') >= 2)
