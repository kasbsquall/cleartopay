#!/usr/bin/env bash
# Day-1 feasibility probes. Run on the Vultr VM as a non-root sudo user:
#   set -a; . ./.env; set +a; bash deploy/probes.sh | tee probes-$(date +%F).log
# Each probe prints PASS, FAIL or INFO and keeps going.
set -u

say() { printf '\n== %s\n' "$*"; }
API="${INFERENCE_BASE_URL:-https://api.vultrinference.com/v1}"

say "1. KVM for microVMs"
if [ -e /dev/kvm ]; then ls -l /dev/kvm; echo "PASS /dev/kvm present"; else echo "FAIL /dev/kvm missing -> plan B: Docker + gVisor"; fi
grep -E -c '(vmx|svm)' /proc/cpuinfo | sed 's/^/INFO cpu virt flags: /'

say "2. Official sources reachable from this IP"
for url in \
  "https://sanctionssearch.ofac.treas.gov/" \
  "https://sam.gov/search/?index=ex" \
  "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName"; do
  code=$(curl -s -o /dev/null -m 25 -A "Mozilla/5.0" -w '%{http_code}' "$url")
  echo "INFO $code $url"
done

say "3. Inference: model list (public)"
curl -s -m 20 "$API/models" | head -c 300; echo

if [ -z "${VULTR_INFERENCE_API_KEY:-}" ]; then
  echo "FAIL VULTR_INFERENCE_API_KEY not set; skipping authenticated probes"
  exit 0
fi
AUTH="Authorization: Bearer $VULTR_INFERENCE_API_KEY"

chat() { # model, json-content
  curl -s -m 120 "$API/chat/completions" -H "$AUTH" -H "Content-Type: application/json" \
    -d "{\"model\":\"$1\",\"max_tokens\":60,\"messages\":[{\"role\":\"user\",\"content\":$2}]}"
}

say "4. Inference: text call returns the model we asked for"
for m in glm-5.3 qwen3.8-27b mimo-v2.6-pro; do
  out=$(chat "$m" '"Reply with the single word: ready"')
  got=$(printf '%s' "$out" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("model"),"|",d["choices"][0]["message"]["content"][:40])' 2>/dev/null || printf '%s' "$out" | head -c 200)
  echo "INFO $m -> $got"
done

say "5. Inference: misspelled model id (silent fallback?)"
chat "qwen3.8-27b-typo" '"hi"' | head -c 300; echo

say "6. Inference: base64 PNG through image_url"
IMG=$(python3 - <<'PY'
import base64, struct, zlib
w, h = 64, 32
raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
print(base64.b64encode(png).decode())
PY
)
for m in qwen3.8-27b mimo-v2.6-pro; do
  out=$(chat "$m" "[{\"type\":\"text\",\"text\":\"What single color fills this image? One word.\"},{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/png;base64,$IMG\"}}]")
  echo "INFO $m -> $(printf '%s' "$out" | head -c 300)"
done

say "7. Decisions endpoint (/v1/systemone) with clef"
curl -s -m 60 "$API/systemone" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"model":"clef","state":{"page":"Your search for ACME HOLDINGS returned 0 results."},"questions":{"match":{"type":"noul","instructions":"Does the page show at least one matching record?"}}}' | head -c 400; echo

say "8. Usage so far"
curl -s -m 20 "$API/usage" -H "$AUTH" | head -c 400; echo

echo; echo "done"
