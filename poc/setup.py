"""
PoC Scripts — Setup & Requirements
===================================
Jalankan file ini untuk verifikasi dependencies sebelum demo.
"""

# Requirements untuk semua PoC scripts
REQUIREMENTS = """
requests>=2.31.0
PyJWT>=2.8.0
websockets>=12.0
"""

# Simpan ke requirements.txt
with open("requirements.txt", "w") as f:
    f.write(REQUIREMENTS.strip())

print("Requirements file dibuat: requirements.txt")
print("\nInstall dengan:")
print("  pip install -r requirements.txt")
print("\nScripts yang tersedia:")
print("  HIGH-002-token-still-valid-after-logout.py")
print("  HIGH-004-db-pool-exhaustion.py")
print("  HIGH-005-websocket-no-auth.py")
print("  HIGH-006-cors-demo.sh")
print("  MEDIUM-007-auto-create-demo.py")
print("  MEDIUM-009-no-rate-limiting.py")
print("  MEDIUM-011-jwt-token-forgery.py")
print("\nLihat DEMO-ANALYSIS.md untuk panduan lengkap.")
