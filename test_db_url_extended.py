from app.database import get_async_database_url


def test_url_transformation_extended():
    # Test 1: postgresql with sslmode and channel_binding
    url1 = "postgresql://user:pass@localhost/db?sslmode=require&channel_binding=prefer"
    expected1 = "postgresql+asyncpg://user:pass@localhost/db?ssl=true"
    result1 = get_async_database_url(url1)
    assert result1 == expected1
    print(f"Test 1 passed: {url1} -> {result1}")

    # Test 2: all problematic params
    url2 = "postgres://user:pass@localhost/db?sslmode=require&channel_binding=require&gssencmode=prefer&target_session_attrs=read-write&foo=bar"
    result2 = get_async_database_url(url2)
    assert "ssl=true" in result2
    assert "foo=bar" in result2
    assert "channel_binding" not in result2
    assert "gssencmode" not in result2
    assert "target_session_attrs" not in result2
    assert result2.startswith("postgresql+asyncpg://")
    print(f"Test 2 passed: {url2} -> {result2}")

if __name__ == "__main__":
    test_url_transformation_extended()
