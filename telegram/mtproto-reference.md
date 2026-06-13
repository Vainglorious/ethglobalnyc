# Telegram MTProto — server reference

> **Note:** Everything in this file is Telegram's *public* infrastructure — the
> same for every user and **already built into Telethon**. You do **not** need to
> configure these to use `polygun/pg.py`. Saved here only for reference.
>
> The credentials we actually need are different: **`api_id` + `api_hash`** from
> https://my.telegram.org → **API development tools** (put them in `polygun/.env`).
> Those identify *your app*; the keys below identify *Telegram's servers*.

## Data centers (we use PRODUCTION)

- **Production:** `149.154.167.50:443` (DC2) ← Telethon's default; this is us.
- Test: `149.154.167.40:443` — only for Telegram *test* accounts; not used.

## Telegram server RSA public keys (public, bundled in Telethon)

Production (149.154.167.50:443):
```
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEA6LszBcC1LGzyr992NzE0ieY+BSaOW622Aa9Bd4ZHLl+TuFQ4lo4g
5nKaMBwK/BIb9xUfg0Q29/2mgIR6Zr9krM7HjuIcCzFvDtr+L0GQjae9H0pRB2OO
62cECs5HKhT5DZ98K33vmWiLowc621dQuwKWSQKjWf50XYFw42h21P2KXUGyp2y/
+aEyZ+uVgLLQbRA1dEjSDZ2iGRy12Mk5gpYc397aYp438fsJoHIgJ2lgMv5h7WY9
t6N/byY9Nw9p21Og3AoXSL2q/2IJ1WRUhebgAdGVMlV1fkuOQoEzR7EdpqtQD9Cs
5+bfo3Nhmcyvk5ftB0WkJ9z6bNZ7yxrP8wIDAQAB
-----END RSA PUBLIC KEY-----
```

Test (149.154.167.40:443):
```
-----BEGIN RSA PUBLIC KEY-----
MIIBCgKCAQEAyMEdY1aR+sCR3ZSJrtztKTKqigvO/vBfqACJLZtS7QMgCGXJ6XIR
yy7mx66W0/sOFa7/1mAZtEoIokDP3ShoqF4fVNb6XeqgQfaUHd8wJpDWHcR2OFwv
plUUI1PLTktZ9uW2WE23b+ixNwJjJGwBDJPQEQFBE+vfmH0JP503wr5INS1poWg/
j25sIWeYPHYeOrFp/eXaqhISP6G+q2IeTaWTXpwZj4LzXq5YOpk4bYEQ6mvRq7D1
aHWfYmlEGepfaYR8Q0YqvvhYtMte3ITnuSJs171+GDqpdKcSwHnd6FudwGO4pcCO
j4WcDuXc2CTHgH8gFTNhp/Y8/SpDOhvn9QIDAQAB
-----END RSA PUBLIC KEY-----
```

## What to actually do

1. https://my.telegram.org → API development tools → create app → copy
   **api_id** + **api_hash**.
2. Put them in `polygun/.env` (`TG_API_ID`, `TG_API_HASH`, `TG_PHONE`).
3. `polygun/.venv/bin/python polygun/pg.py login`

The Telethon controller lives in `polygun/` (see `polygun/README.md`).
