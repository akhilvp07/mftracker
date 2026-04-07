# Kite Connect API Setup Information

## Overview
Kite Connect is a REST-like API platform for trading and investment data provided by Zerodha. It allows developers to build trading applications, access market data, place orders, and manage portfolios programmatically.

## Prerequisites

### Trading Account Requirements
- An active Zerodha trading account
- Account with 2FA TOTP enabled
  - Setup guide: https://support.zerodha.com/category/trading-and-markets/general-kite/login-credentials-of-trading-platforms/articles/time-based-otp-setup

### Developer Account Setup
1. Create Developer Account: Visit [Kite Connect Developer Portal](https://developers.kite.trade/login) and sign up
2. App Creation: Log in and create a new app to get your API credentials
3. Set Redirect URL: Configure the URL where user will be redirected after authentication
4. Get API Keys: Note down your `api_key` and `api_secret` (keep the secret secure)

## Authentication Flow

### Step 1: Redirect to Login
Navigate user to:
```
https://kite.zerodha.com/connect/login?v=3&api_key=xxx
```

Optional redirect parameter:
```
https://kite.zerodha.com/connect/login?v=3&api_key=xxx&redirect_params=some%3DX%26more%3DY
```

### Step 2: Receive Request Token
After successful login, Zerodha redirects to your registered URL with:
- `request_token` in query parameters
- Any `redirect_params` you included

### Step 3: Generate Checksum
Create SHA-256 checksum:
```
checksum = SHA256(api_key + request_token + api_secret)
```

### Step 4: Exchange for Access Token
POST to token endpoint:
```bash
curl https://api.kite.trade/session/token \
  -H "X-Kite-Version: 3" \
  -d "api_key=xxx" \
  -d "request_token=yyy" \
  -d "checksum=zzz"
```

Response:
```json
{
  "status": "success",
  "data": {
    "user_type": "individual",
    "email": "XXXXXX",
    "user_name": "Kite Connect",
    "user_shortname": "Connect",
    "broker": "ZERODHA",
    "exchanges": ["NSE", "NFO", "BFO", "CDS", "BSE", "MCX", "BCD", "MF"],
    "products": ["CNC", "NRML", "MIS", "BO", "CO"],
    "order_types": ["MARKET", "LIMIT", "SL", "SL-M"],
    "avatar_url": "abc",
    "user_id": "XX0000",
    "api_key": "XXXXXX",
    "access_token": "XXXXXX",
    "public_token": "XXXXXXXX",
    "enctoken": "XXXXXX",
    "refresh_token": "",
    "silo": "",
    "login_time": "2021-01-01 16:15:14",
    "meta": {"demat_consent": "physical"}
  }
}
```

## Official SDKs

### Python
- Repository: https://github.com/zerodha/pykiteconnect
- Examples: https://github.com/zerodha/pykiteconnect/tree/master/examples
- Documentation: https://kite.trade/docs/pykiteconnect/v4/

### Go
- Repository: https://github.com/zerodha/gokiteconnect
- Examples: https://github.com/zerodha/gokiteconnect/tree/master/examples
- Documentation: https://pkg.go.dev/github.com/zerodha/gokiteconnect/v4

### Java
- Repository: https://github.com/zerodha/javakiteconnect
- Examples: https://github.com/zerodha/javakiteconnect/tree/master/sample/src
- Documentation: https://kite.trade/docs/javakiteconnect/v3/

### PHP
- Repository: https://github.com/zerodha/phpkiteconnect
- Examples: https://github.com/zerodha/phpkiteconnect/tree/master/examples
- Documentation: https://kite.trade/docs/phpkiteconnect/v3/classes/KiteConnect-KiteConnect.html

### Node.js
- Repository: https://github.com/zerodha/kiteconnectjs
- Examples: https://github.com/zerodha/kiteconnectjs/blob/master/examples
- Documentation: https://kite.trade/docs/kiteconnectjs/v3/

### .NET
- Repository: https://github.com/zerodha/dotnetkiteconnect
- Examples: https://github.com/zerodha/dotnetkiteconnect/tree/master/KiteConnectSample
- Documentation: https://kite.trade/docs/kiteconnectdotnet/v3/

## API Endpoints

### Root API Endpoint
```
https://api.kite.trade/
```

### Requesting a Particular Version
Include header in all requests:
```
X-Kite-Version: 3
```

## Important Security Notes

⚠️ **Never expose your `api_secret`** by embedding it in a mobile app or client-side application

⚠️ **Do not expose the `access_token`** you obtain for a session to the public

⚠️ Always use HTTPS for all API communications

## Useful Resources

- Developer Community Forum: https://kite.trade/forum/discussion/4732/frequently-asked-questions-faqs
- Login Flow Webinar: https://www.youtube.com/watch?v=9vzd289Eedk
- Main Documentation: https://kite.trade/docs/connect/v3/

## Rate Limits

- Check the latest rate limits in the official documentation
- Implement proper rate limiting in your application
- Use websockets for real-time data instead of polling

## Common Use Cases

1. **Market Data**: Fetch historical prices, market depth, quotes
2. **Order Management**: Place, modify, cancel orders
3. **Portfolio Tracking**: Get holdings, positions, margins
4. **Trading Algorithms**: Implement automated trading strategies
5. **Analysis Tools**: Build technical and fundamental analysis tools
