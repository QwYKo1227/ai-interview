def validate_password_policy(password: str) -> str:
    password_bytes = len(password.encode("utf-8"))
    if password_bytes < 12:
        raise ValueError("密码必须至少为 12 个 UTF-8 字节")
    if password_bytes > 72:
        raise ValueError("密码最多为 72 个 UTF-8 字节")
    if not any(character.isalpha() for character in password):
        raise ValueError("密码必须包含字母")
    if not any(character.isdigit() for character in password):
        raise ValueError("密码必须包含数字")
    return password
