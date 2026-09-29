#!/bin/bash
# Quick start script for Redis Prompt Cache

set -e

COMPOSE_FILE="docker-compose-redis.yml"

echo "🚀 Starting Redis + Redis Insight..."

# Start services
docker-compose -f "$COMPOSE_FILE" up -d

# Wait for Redis to be ready
echo "⏳ Waiting for Redis to be healthy..."
for i in {1..30}; do
    if docker exec cartwheel-redis redis-cli -a prompts123 ping > /dev/null 2>&1; then
        echo "✓ Redis is ready"
        break
    fi
    sleep 1
done

# Wait for Redis Insight
echo "⏳ Waiting for Redis Insight..."
sleep 3

# Try to open Redis Insight in browser
REDIS_INSIGHT_URL="http://localhost:5540"
echo ""
echo "✓ Services started!"
echo ""
echo "📊 Redis Insight: $REDIS_INSIGHT_URL"
echo "🔴 Redis Server: localhost:6379 (password: prompts123)"
echo ""
echo "Next steps:"
echo "  1. Add prompts: python3 prompt_cache.py import sample_prompts.txt"
echo "  2. View in Redis Insight:"
echo "     - Open http://localhost:5540"
echo "     - Click 'Add Redis Database'"
echo "     - Host: localhost, Port: 6379, Password: prompts123"
echo "  3. Search: python3 prompt_cache.py search 'keyword'"
echo ""
echo "To stop services: docker-compose -f $COMPOSE_FILE down"
echo ""

# Try to open in browser
if command -v open > /dev/null 2>&1; then
    echo "Opening Redis Insight in browser..."
    open "$REDIS_INSIGHT_URL"
elif command -v xdg-open > /dev/null 2>&1; then
    xdg-open "$REDIS_INSIGHT_URL"
fi
