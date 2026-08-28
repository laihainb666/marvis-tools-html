#!/usr/bin/env bash
# ============================================================
# mouse-format.sh —— 万能文件格式转换（Shell 版本）
# ============================================================
# 与 mouse-format-lite (Python) 同一格式覆盖目标：
#   图片 / 文本 / 电子书 / Office / PDF / 音视频 / ZIP
# 转换引擎（自动探测）：
#   1) 图片/音视频 -> ffmpeg（系统命令，或 imageio-ffmpeg 内置静态二进制）
#   2) 文档/PDF/电子书/ZIP -> python3 + convert.py（可选，存在时启用）
#
# 用法：
#   ./mouse-format.sh <文件...> --to <格式> [-o 输出路径]
#   ./mouse-format.sh web [端口]          # 启动 WebUI
#   ./mouse-format.sh doctor              # 环境自检
#   ./mouse-format.sh formats             # 查看格式支持
#
# 示例：
#   ./mouse-format.sh a.png --to webp
#   ./mouse-format.sh a.heic --to jpg
#   ./mouse-format.sh a.png b.png --to pdf
#   ./mouse-format.sh video.mp4 --to mp3
#   ./mouse-format.sh book.pdf --to png
#   ./mouse-format.sh book.pdf --to docx
#   ./mouse-format.sh a.txt --to epub
# ============================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONVERT_PY="${SCRIPT_DIR}/convert.py"

# ------------------------------------------------------------ 引擎探测

find_ffmpeg() {
  local exe
  if command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg"; return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    exe="$(python3 - <<'PY' 2>/dev/null
try:
    import imageio_ffmpeg, os
    e = imageio_ffmpeg.get_ffmpeg_exe()
    if e and os.path.isfile(e): print(e)
except Exception: pass
PY
)"
    if [ -n "$exe" ]; then echo "$exe"; return 0; fi
  fi
  echo ""; return 1
}

have_py_core() {
  [ -f "$CONVERT_PY" ] && command -v python3 >/dev/null 2>&1
}

# ------------------------------------------------------------ 类型判定

ext_of() { echo "${1##*.}" | tr 'A-Z' 'a-z'; }

detect_type() {
  local ext; ext="$(ext_of "$1")"
  case "$ext" in
    jpg|jpeg|png|webp|avif|bmp|gif|tif|tiff|ico|tga|heic|heif) echo "image" ;;
    mp4|avi|mkv|mov|webm|flv|wmv|m4v|mpg|mpeg|ts|3gp)        echo "video" ;;
    mp3|wav|flac|ogg|aac|m4a|wma|opus)                       echo "audio" ;;
    pdf)                                                      echo "pdf" ;;
    txt|md|markdown|html|htm|json|csv|log|xml|yaml|yml)      echo "text" ;;
    epub|mobi)                                                echo "ebook" ;;
    docx|xlsx|xlsm|pptx)                                      echo "office" ;;
    doc|odt|rtf|xls|ods|ppt|odp)                              echo "legacydoc" ;;
    zip)                                                      echo "archive" ;;
    *) echo "unknown" ;;
  esac
}

# ------------------------------------------------------------ ffmpeg 直转（图片/音视频）

ff_convert() {
  local ff="$1" src="$2" dst="$3" out="$4" srctype="$5"
  case "$srctype:$dst" in
    image:gif)
      "$ff" -y -i "$src" -loop 0 -f gif "$out" >/dev/null 2>&1 && echo "$out" && return 0 ;;
    image:*)
      "$ff" -y -i "$src" "$out" >/dev/null 2>&1 && echo "$out" && return 0 ;;
    video:gif)
      "$ff" -y -i "$src" -vf "fps=10,scale=trunc(iw/2)*2:trunc(ih/2)*2" -f gif "$out" >/dev/null 2>&1 && echo "$out" && return 0 ;;
    video:*|audio:*)
      "$ff" -y -i "$src" -map 0:a:0 -b:a 192k "$out" >/dev/null 2>&1 && echo "$out" && return 0 ;;
  esac
  return 1
}

# ------------------------------------------------------------ 主流程

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

show_formats() {
  echo "== 输入类型 -> 常见目标格式 =="
  echo "图片  : jpg/png/webp/avif/bmp/gif/tiff/ico/tga/heic/heif 互转；多图->pdf；图->zip"
  echo "视频  : mp4/avi/mkv/mov/webm/flv/wmv/m4v/mpg 互转；->gif；->mp3/wav/aac 等音频"
  echo "音频  : mp3/wav/flac/ogg/aac/m4a/wma/opus 互转"
  echo "PDF   : ->txt/docx/xlsx/html/png/jpg/webp/split(拆页)/图片"
  echo "文本  : ->md/txt/html/pdf/docx/epub（txt/md/html/json/csv 等）"
  echo "电子书: epub/mobi ->txt/md"
  echo "Office: docx->md/txt/html/pdf；xlsx->csv/md/pdf；pptx->md/txt/html/pdf"
  echo "ZIP   : 打包任意文件；->pdf（图片压缩包合并）"
  echo "注：图片/音视频由 ffmpeg 直转；PDF/Office/电子书/ZIP 需 python3 + convert.py"
}

doctor() {
  echo "== mouse-format.sh 环境自检 =="
  local ff; ff="$(find_ffmpeg)"
  if [ -n "$ff" ]; then echo "[OK] ffmpeg: $ff"; else echo "[X] ffmpeg 未找到（可用 pip install imageio-ffmpeg 提供）"; fi
  if have_py_core; then
    echo "[OK] python3 + convert.py 可用（文档/PDF/电子书/ZIP 转换）"
  else
    echo "[!] 未找到 convert.py 或 python3（仅图片/音视频可用）"
  fi
}

convert_one() {
  local src="$1" dst="$2" out="$3"
  local type; type="$(detect_type "$src")"
  local ff; ff="$(find_ffmpeg)"

  # 图片/音视频：优先 ffmpeg 直转
  case "$type" in
    image|video|audio)
      if [ -n "$ff" ]; then
        if ff_convert "$ff" "$src" "$dst" "$out" "$type"; then
          echo "[OK] $src -> $out (ffmpeg)"
          return 0
        fi
        echo "[!] ffmpeg 直转失败，尝试 python 核心…"
      fi
      ;;
  esac

  # 其他：python 核心
  if have_py_core; then
    if [ "$type" = "image" ] || [ "$type" = "video" ] || [ "$type" = "audio" ]; then
      python3 "$CONVERT_PY" "$src" --to "$dst" -o "$out" >/dev/null 2>&1 && { echo "[OK] $src -> $out (python)"; return 0; }
      echo "[X] 转换失败: $src -> $dst"
      return 1
    fi
    python3 "$CONVERT_PY" "$src" --to "$dst" -o "$out" >/dev/null 2>&1 && { echo "[OK] $src -> $out (python)"; return 0; }
    echo "[X] 转换失败: $src -> $dst"
    return 1
  fi

  echo "[X] 无法转换：缺少 ffmpeg 且无 python 核心。运行 ./mouse-format.sh doctor 查看。"
  return 1
}

# ------------------------------------------------------------ 入口

CMD="${1:-}"
if [ "$CMD" = "doctor" ]; then doctor; exit 0; fi
if [ "$CMD" = "formats" ]; then show_formats; exit 0; fi
if [ "$CMD" = "web" ]; then
  PORT="${2:-8000}"
  if have_py_core; then
    echo "启动 WebUI: http://0.0.0.0:${PORT} （Ctrl+C 停止）"
    exec python3 "${SCRIPT_DIR}/webui.py" "$PORT"
  else
    echo "[X] WebUI 需要 python3 + convert.py"; exit 1
  fi
fi
if [ "$CMD" = "-h" ] || [ "$CMD" = "--help" ]; then usage; exit 0; fi

# 解析参数：<文件...> --to <格式> [-o 输出]
FILES=(); DST=""; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --to) shift; DST="${1:-}";;
    -o) shift; OUT="${1:-}";;
    -h|--help) usage; exit 0;;
    *) FILES+=("$1");;
  esac
  shift
done

if [ "${#FILES[@]}" -eq 0 ] || [ -z "$DST" ]; then
  echo "用法: $0 <文件...> --to <格式> [-o 输出]" >&2
  echo "更多: $0 --help" >&2
  exit 1
fi

DST="$(echo "$DST" | tr 'A-Z' 'a-z')"

if [ "${#FILES[@]}" -eq 1 ]; then
  SRC="${FILES[0]}"
  [ -f "$SRC" ] || { echo "[X] 文件不存在: $SRC"; exit 1; }
  if [ -z "$OUT" ]; then
    OUT="${SRC%.*}.${DST}"
  fi
  convert_one "$SRC" "$DST" "$OUT" || exit 1
else
  # 多文件：仅支持 ->pdf / ->zip
  case "$DST" in
    pdf|zip)
      if have_py_core; then
        python3 "$CONVERT_PY" "${FILES[@]}" --to "$DST" -o "$OUT" >/dev/null 2>&1 \
          && { echo "[OK] ${#FILES[@]} 个文件 -> ${OUT:-合并.$DST} (python)"; exit 0; }
        echo "[X] 合并失败"; exit 1
      else
        echo "[X] 多文件合并需要 python3 + convert.py"; exit 1
      fi
      ;;
    *)
      echo "[X] 多文件仅支持 --to pdf / --to zip"; exit 1;;
  esac
fi
