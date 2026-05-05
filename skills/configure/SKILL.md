# /wechat:configure

Configure the WeChat channel's connection to the Wisdom server.

## Usage

```
/wechat:configure <api_url> [token]
```

## Examples

```
/wechat:configure http://localhost:8000
/wechat:configure http://localhost:8000 my-secret-token
/wechat:configure http://192.168.1.100:8000 my-token
```

## What it does

Writes `WISDOM_API_URL` and `WISDOM_API_TOKEN` to `~/.claude/channels/wechat/.env`.

## Instructions for Claude

When the user runs `/wechat:configure`, parse the arguments and write the `.env` file:

1. Extract the API URL (first argument, required)
2. Extract the API token (second argument, optional)
3. Create the directory `~/.claude/channels/wechat/` if it doesn't exist
4. Write the `.env` file with:
   ```
   WISDOM_API_URL=<url>
   WISDOM_API_TOKEN=<token>
   ```
5. Set file permissions to owner-only (chmod 600) on non-Windows systems
6. Confirm to the user and remind them to restart with `--channels`

**Security:** Never echo the token back to the user. Just confirm it was saved.
