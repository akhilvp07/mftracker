#!/bin/bash
# Script to run migrations on Vercel production

echo "Running migrations on Vercel..."

# Make POST request to run migrations
response=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  https://mftracker-zeta.vercel.app/api/migrate)

# Parse response
status=$(echo $response | grep -o '"status":"[^"]*' | cut -d'"' -f4)
message=$(echo $response | grep -o '"message":"[^"]*' | cut -d'"' -f4)

if [ "$status" = "success" ]; then
  echo "✅ Migrations applied successfully!"
  echo "Message: $message"
else
  echo "❌ Migration failed!"
  echo "Message: $message"
  exit 1
fi
