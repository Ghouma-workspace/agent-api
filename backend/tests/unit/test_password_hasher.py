from app.infrastructure.security.jwt import PasswordHasher


def test_hash_verifies_correct_password():
    hasher = PasswordHasher()
    hashed = hasher.hash("correct horse battery staple")
    assert hasher.verify(hashed, "correct horse battery staple") is True


def test_hash_rejects_wrong_password():
    hasher = PasswordHasher()
    hashed = hasher.hash("correct horse battery staple")
    assert hasher.verify(hashed, "wrong password") is False


def test_hash_output_is_not_plaintext():
    hasher = PasswordHasher()
    hashed = hasher.hash("hunter2")
    assert "hunter2" not in hashed
