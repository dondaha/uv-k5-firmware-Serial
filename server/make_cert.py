import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

def generate_self_signed_cert():
    print("正在生成本地测试用的 HTTPS 证书...")
    
    # 生成私钥
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 生成自签名证书
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"UV-K5-Remote-Radio"),
    ])
    
    # 确保证书自生成之时起有效（预留一点网络同步时间）
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow() - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365) # 有效期一年
    ).sign(key, hashes.SHA256())

    # 写入私钥 (key.pem)
    with open("key.pem", "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # 写入证书 (cert.pem)
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
        
    print("✅ 成功生成 cert.pem 和 key.pem !")
    print("   下次启动 main.py 将自动以 HTTPS 模式运行。")

if __name__ == "__main__":
    generate_self_signed_cert()
