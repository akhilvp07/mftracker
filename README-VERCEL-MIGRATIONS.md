# Running Migrations on Vercel

## Option 1: Using Vercel CLI (Recommended)

If you have Vercel CLI installed:

```bash
# 1. Install Vercel CLI if not already installed
npm i -g vercel

# 2. Link to your project (if not already linked)
vercel link

# 3. Run migrations remotely
vercel env pull
vercel run --no-cache python manage.py migrate
```

## Option 2: Using curl (After deploy completes)

Once the API endpoint is deployed:

```bash
# Run migrations via API
curl -X POST https://mftracker-zeta.vercel.app/api/migrate
```

## Option 3: Using the provided script

```bash
# Make script executable
chmod +x scripts/run-migrations.sh

# Run migrations
./scripts/run-migrations.sh
```

## Option 4: Using Vercel Dashboard

1. Go to Vercel Dashboard
2. Select your project
3. Go to Functions tab
4. Find the migrate function
5. Click "Invoke" with POST method

## Troubleshooting

If migrations fail:
1. Check if the deploy completed successfully
2. Verify the API endpoint exists
3. Check Vercel function logs for errors
