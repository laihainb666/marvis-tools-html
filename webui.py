#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mouse-format-lite Web UI —— 网页版离线格式转换（纯标准库实现）
================================================================
用法：python3 webui.py [端口=8000]
然后在浏览器打开 http://127.0.0.1:8000 ，上传文件 -> 选目标格式 -> 转换 -> 下载。
完全本地运行，不依赖任何外部服务。

注意：文件上传大小限制由本机 http.server 默认处理；大文件建议使用 CLI 版。
"""

import io
import os
import re
import sys
import tempfile
import time
import urllib.parse
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import convert  # 复用 CLI 版转换引擎

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "mfl_uploads")
RESULT_DIR = os.path.join(WORK_DIR, "converted")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>鼠鼠格式转换 · 离线版</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; min-height:100vh;
         background:linear-gradient(135deg,#0f172a,#1e293b); color:#e2e8f0; display:flex; align-items:center; justify-content:center; padding:24px; }
  .box { background:#1e293b; border:1px solid #334155; border-radius:20px; padding:40px; width:100%; max-width:560px; box-shadow:0 20px 60px rgba(0,0,0,.4); }
  h1 { font-size:24px; margin-bottom:6px; }
  h1 span { color:#38bdf8; }
  p.sub { color:#94a3b8; font-size:13px; margin-bottom:28px; }
  label { display:block; font-size:13px; color:#94a3b8; margin-bottom:8px; }
  .field { margin-bottom:20px; }
  input[type=file], select {
    width:100%; padding:12px 14px; border-radius:12px; border:1px solid #334155; background:#0f172a; color:#e2e8f0; font-size:14px; outline:none;
  }
  input[type=file]::file-selector-button { background:#0ea5e9; border:none; color:#fff; padding:8px 16px; border-radius:8px; margin-right:12px; cursor:pointer; }
  button { width:100%; padding:14px; border:none; border-radius:12px; background:#0ea5e9; color:#fff; font-size:15px; font-weight:600; cursor:pointer; }
  button:hover { background:#0284c7; }
  .msg { margin-top:20px; padding:14px; border-radius:12px; font-size:14px; word-break:break-all; }
  .msg.ok { background:rgba(34,197,94,.12); border:1px solid rgba(34,197,94,.4); color:#86efac; }
  .msg.err { background:rgba(239,68,68,.12); border:1px solid rgba(239,68,68,.4); color:#fca5a5; }
  a.dl { display:inline-block; margin-top:8px; color:#38bdf8; }
  .footer { margin-top:24px; font-size:12px; color:#64748b; text-align:center; }
</style>
</head>
<body>
<div class="box">
  <h1>鼠鼠格式转换 <span>· 离线版</span></h1>
  <p class="sub">复刻自 FlyingMouse Format（飞鼠格式）· 图片/音视频/PDF/文档互转 · 无网络无账号</p>
  <form action="/convert" method="post" enctype="multipart/form-data">
    <div class="field">
      <label>选择文件（可多选，多选仅支持合成 PDF）</label>
      <input type="file" name="files" multiple required>
    </div>
    <div class="field">
      <label>目标格式</label>
      <select name="target">
        <optgroup label="图片">
          <option value="jpg">jpg（图片）</option>
          <option value="png">png（图片/PDF导出）</option>
          <option value="webp">webp（图片）</option>
          <option value="avif">avif（图片）</option>
          <option value="gif">gif（动图/视频转GIF）</option>
          <option value="bmp">bmp（图片）</option>
          <option value="tiff">tiff（图片）</option>
          <option value="ico">ico（图标）</option>
          <option value="pdf">pdf（图片合成/文档目标）</option>
        </optgroup>
        <optgroup label="文本/电子书">
          <option value="txt">txt（文本）</option>
          <option value="md">md（Markdown）</option>
          <option value="html">html（网页）</option>
          <option value="epub">epub（电子书）</option>
        </optgroup>
        <optgroup label="Office">
          <option value="docx">docx（Word）</option>
          <option value="csv">csv（表格）</option>
          <option value="xlsx">xlsx（表格）</option>
        </optgroup>
        <optgroup label="PDF">
          <option value="split">split（PDF逐页拆分）</option>
        </optgroup>
        <optgroup label="音视频">
          <option value="mp4">mp4（视频）</option>
          <option value="webm">webm（视频）</option>
          <option value="avi">avi（视频）</option>
          <option value="mkv">mkv（视频）</option>
          <option value="mov">mov（视频）</option>
          <option value="mp3">mp3（音频）</option>
          <option value="wav">wav（音频）</option>
          <option value="flac">flac（音频）</option>
          <option value="ogg">ogg（音频）</option>
          <option value="m4a">m4a（音频）</option>
          <option value="opus">opus（音频）</option>
          <option value="wma">wma（音频）</option>
        </optgroup>
        <optgroup label="压缩包">
          <option value="zip">zip（任意文件打包）</option>
        </optgroup>
      </select>
    </div>
    <button type="submit">开始转换</button>
  </form>
  <div id="msg" class="msg" style="display:none;"></div>
  <div class="footer">Marvis 复刻 · mouse-format-lite</div>
</div>
<script>
document.querySelector('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = document.getElementById('msg');
  msg.style.display = 'block'; msg.className = 'msg'; msg.textContent = '正在转换，请稍候...';
  const resp = await fetch('/convert', { method:'POST', body: new FormData(e.target) });
  const text = await resp.text();
  msg.innerHTML = text;
});
</script>
</body>
</html>
"""


def parse_multipart(body, content_type):
    """用 email 模块解析 multipart/form-data，返回 {字段名: [值]}"""
    raw = b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    msg = message_from_bytes(raw)
    fields = {}
    parts = msg.get_payload() if msg.is_multipart() else [msg]
    if not isinstance(parts, list):
        parts = [parts]
    for part in parts:
        name = part.get_param("name", header="content-disposition")
        if name is None:
            continue
        fname = part.get_filename()
        if fname:
            payload = part.get_payload(decode=True)
            fields.setdefault(name, []).append({"filename": fname, "data": payload})
        else:
            text = part.get_payload(decode=True)
            if text is not None:
                fields[name] = text.decode("utf-8", errors="replace")
    return fields


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(200, HTML_PAGE)
        elif parsed.path == "/download":
            qs = urllib.parse.parse_qs(parsed.query)
            name = qs.get("file", [""])[0]
            safe = os.path.basename(name)
            path = os.path.join(RESULT_DIR, safe)
            if safe and os.path.isfile(path):
                with open(path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(data)
            else:
                self._send(404, "文件不存在或已过期")
        else:
            self._send(404, "Not Found")

    def do_POST(self):
        if self.path != "/convert":
            self._send(404, "Not Found")
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > 1_500_000_000:
            self._send(413, "<div class='msg err'>文件过大</div>")
            return
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        fields = parse_multipart(body, ctype)

        files = fields.get("files", [])
        target = fields.get("target", "png")
        if not files:
            self._send(400, "<div class='msg err'>未收到文件</div>")
            return

        # 保存上传文件
        saved = []
        for f in files:
            name = os.path.basename(re.sub(r"[^\w.\-]", "_", f["filename"]))
            p = os.path.join(UPLOAD_DIR, f"{int(time.time()*1000)}_{name}")
            with open(p, "wb") as fh:
                fh.write(f["data"])
            saved.append(p)

        # 执行转换
        try:
            if len(saved) > 1 and target.lower() == "pdf":
                out = os.path.join(RESULT_DIR, f"merged_{int(time.time())}.pdf")
                convert.images_to_pdf(saved, out)
                results = [out]
            else:
                src = saved[0]
                ext = os.path.splitext(src)[1].lower()
                stype = convert.detect_type(src)
                out = os.path.join(RESULT_DIR, f"{int(time.time()*1000)}_{os.path.basename(src)[:30]}.{target}")

                if stype == "image":
                    if target == "pdf":
                        convert.images_to_pdf([src], out)
                    elif target == "zip":
                        convert.to_zip([src], out)
                    elif target in ("jpg", "jpeg", "png", "webp", "avif", "bmp", "gif", "tiff", "ico"):
                        convert.convert_image(src, target, out)
                    else:
                        raise ValueError(f"图片暂不支持转为 {target}")
                elif stype in ("video", "audio"):
                    convert.convert_media(src, target, out)
                elif stype == "pdf":
                    if target == "txt":
                        convert.pdf_to_text(src, out)
                    elif target == "docx":
                        convert.pdf_to_docx(src, out)
                    elif target == "xlsx":
                        convert.pdf_to_xlsx(src, out)
                    elif target == "html":
                        convert.pdf_to_html(src, out)
                    elif target in ("png", "jpg", "jpeg", "webp", "bmp"):
                        tmp = os.path.join(UPLOAD_DIR, f"pdf_{int(time.time())}")
                        os.makedirs(tmp, exist_ok=True)
                        fmt = "png" if target == "png" else ("jpg" if target in ("jpg", "jpeg") else target)
                        outs = convert.pdf_to_images(src, tmp, fmt)
                        links = "".join(
                            f'<a class="dl" href="/download?file={urllib.parse.quote(os.path.basename(p))}">下载 {os.path.basename(p)}</a><br>'
                            for p in outs
                        )
                        self._send(200, f"<div class='msg ok'>PDF 已导出 {len(outs)} 页：<br>{links}</div>")
                        return
                    elif target == "split":
                        tmp = os.path.join(RESULT_DIR, f"split_{int(time.time())}")
                        os.makedirs(tmp, exist_ok=True)
                        outs = convert.pdf_split(src, tmp)
                        links = "".join(
                            f'<a class="dl" href="/download?file={urllib.parse.quote(os.path.basename(p))}">下载 {os.path.basename(p)}</a><br>'
                            for p in outs
                        )
                        self._send(200, f"<div class='msg ok'>PDF 已拆分为 {len(outs)} 页：<br>{links}</div>")
                        return
                    else:
                        raise ValueError(f"PDF 暂不支持转为 {target}")
                elif stype == "text":
                    if target in ("txt", "md", "log"):
                        write_txt = os.path.join(RESULT_DIR, f"{int(time.time()*1000)}_{os.path.basename(src)[:30]}.{'md' if target == 'md' else 'txt'}")
                        open(write_txt, "w", encoding="utf-8").write(convert.to_markdown(src))
                        out = write_txt
                    elif target == "html":
                        convert.to_html(src, out)
                    elif target == "pdf":
                        convert.text_to_pdf(convert.to_markdown(src), out, os.path.basename(src))
                    elif target == "docx":
                        convert.text_to_docx(convert.to_markdown(src), out)
                    elif target == "epub":
                        convert.text_to_epub(convert.to_markdown(src), out, os.path.basename(src))
                    else:
                        raise ValueError(f"文本暂不支持转为 {target}")
                elif stype == "doc":
                    if ext in (".docx",):
                        if target in ("txt", "md"):
                            write_txt = os.path.join(RESULT_DIR, f"{int(time.time()*1000)}_{os.path.basename(src)[:30]}.{'md' if target == 'md' else 'txt'}")
                            open(write_txt, "w", encoding="utf-8").write(convert.docx_to_markdown(src))
                            out = write_txt
                        elif target == "html":
                            tmp = os.path.join(UPLOAD_DIR, f"tmp_{int(time.time())}.md")
                            open(tmp, "w", encoding="utf-8").write(convert.docx_to_markdown(src))
                            convert.to_html(tmp, out)
                        elif target == "pdf":
                            convert.text_to_pdf(convert.docx_to_markdown(src), out, os.path.basename(src))
                        else:
                            raise ValueError(f"docx 暂不支持转为 {target}")
                    elif ext in (".xlsx", ".xlsm"):
                        if target == "csv":
                            convert.xlsx_to_csv(src, out)
                        elif target in ("txt", "md"):
                            write_txt = os.path.join(RESULT_DIR, f"{int(time.time()*1000)}_{os.path.basename(src)[:30]}.{'md' if target == 'md' else 'txt'}")
                            open(write_txt, "w", encoding="utf-8").write(convert.xlsx_to_markdown(src))
                            out = write_txt
                        elif target == "html":
                            convert.xlsx_to_html(src, out)
                        elif target == "pdf":
                            convert.text_to_pdf(convert.xlsx_to_markdown(src), out, os.path.basename(src))
                        else:
                            raise ValueError(f"xlsx 暂不支持转为 {target}")
                    elif ext == ".pptx":
                        if target in ("txt", "md"):
                            write_txt = os.path.join(RESULT_DIR, f"{int(time.time()*1000)}_{os.path.basename(src)[:30]}.{'md' if target == 'md' else 'txt'}")
                            open(write_txt, "w", encoding="utf-8").write(convert.pptx_to_markdown(src))
                            out = write_txt
                        elif target == "html":
                            tmp = os.path.join(UPLOAD_DIR, f"tmp_{int(time.time())}.md")
                            open(tmp, "w", encoding="utf-8").write(convert.pptx_to_markdown(src))
                            convert.to_html(tmp, out)
                        elif target == "pdf":
                            convert.text_to_pdf(convert.pptx_to_markdown(src), out, os.path.basename(src))
                        else:
                            raise ValueError(f"pptx 暂不支持转为 {target}")
                    else:
                        raise ValueError(f"暂不支持该 Office 格式 {ext}")
                elif stype == "ebook":
                    if target in ("txt", "md"):
                        convert.epub_to_markdown(src, out)
                    else:
                        raise ValueError(f"电子书暂不支持转为 {target}")
                elif stype == "archive":
                    if target == "pdf":
                        tmp = os.path.join(UPLOAD_DIR, f"zip_{int(time.time())}")
                        os.makedirs(tmp, exist_ok=True)
                        out = os.path.join(RESULT_DIR, f"merged_{int(time.time())}.pdf")
                        convert.zip_images_to_pdf(src, tmp)
                        import shutil
                        shutil.move(os.path.join(tmp, "merged.pdf"), out)
                    else:
                        raise ValueError("ZIP 输入仅支持转为 pdf")
                elif stype == "unknown" and target == "zip":
                    convert.to_zip([src], out)
                else:
                    raise ValueError(f"无法识别文件类型 {ext}")
                results = [out]
        except Exception as ex:
            self._send(200, f"<div class='msg err'>转换失败：{ex}</div>")
            return

        links = "".join(
            f'<a class="dl" href="/download?file={urllib.parse.quote(os.path.basename(p))}">下载 {os.path.basename(p)}</a><br>'
            for p in results
        )
        self._send(200, f"<div class='msg ok'>转换完成：<br>{links}</div>")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"鼠鼠格式转换 · 离线版已启动：http://127.0.0.1:{port}  （Ctrl+C 退出）")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
