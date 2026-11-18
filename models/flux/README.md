# FLUX.1-schnell Integration

## Overview
- **Model Author**: Black Forest Labs
- **Model**: `FLUX.1-schnell`
- **Model Weights License**: Apache 2.0
- **Execution**: Serverless cloud inference via Cloudflare Workers AI and Hugging Face Inference API.

## Providers
1. **Cloudflare Workers AI**:
   - Model ID: `@cf/black-forest-labs/flux-1-schnell`
   - Endpoint: `https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell`
   - Zero-cost serverless execution within free daily allocation.
2. **Hugging Face Inference API**:
   - Model ID: `black-forest-labs/FLUX.1-schnell`
   - Zero-cost fallback with automatic retry and rate-limit backoff.

## Configuration
```env
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token
HF_TOKEN=your_huggingface_token
```
