import os
import json
import zlib
from itsdangerous import URLSafeTimedSerializer, BadSignature
from flask.sessions import TaggedJSONSerializer

SECRET_KEY = "ivms_secure_secret_2026"
# This is a sample cookie format I've seen in logs
# .eJyt... (length 374)
cookie = ".eJyrViotTi1SslJQcs7PL8pJA9L5SbmV-XklSlZKsTrF-XklSla1SlaGSrU6JYm5qclA_pKVUmxtbS0AqM4V5A.ZkLpRA.VF4D3xPw76pH3jccb7ZXqhs8qmw" # Dummy but correct format

def test_decrypt(c):
    print(f"Testing cookie: {c[:20]}...")
    for digest in ['sha1', 'sha256']:
        for salt in ['cookie-session', 'itsdangerous']:
            try:
                s = URLSafeTimedSerializer(
                    SECRET_KEY, 
                    salt=salt,
                    signer_kwargs={'digest_method': digest}
                )
                # Flask handles decompression in the serializer
                # We can try to use TaggedJSONSerializer which handles dots
                s_tagged = URLSafeTimedSerializer(
                    SECRET_KEY,
                    salt=salt,
                    serializer=TaggedJSONSerializer(),
                    signer_kwargs={'digest_method': digest}
                )
                data = s_tagged.loads(c)
                print(f"SUCCESS with digest={digest}, salt={salt}")
                print(f"Data: {data}")
                return
            except Exception as e:
                pass
    print("FAILED all combinations")

if __name__ == "__main__":
    # In a real scenario, we'd get the cookie from a real session
    pass
