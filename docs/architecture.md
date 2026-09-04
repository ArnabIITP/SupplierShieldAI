# Architecture

SupplierShield uses a React browser client, FastAPI service, Supabase Auth/Postgres/Storage, and local risk inference.

```text
React + Supabase Auth session
          |
          v
FastAPI: validation -> rules -> XGBoost -> Isolation Forest -> explanation
          |                         |
          v                         v
Supabase: workspace-scoped data    Gemini (optional structured explanation)
```

The browser never receives a Supabase secret key, Gemini key, Razorpay secret, or direct access to protected business data. The risk score remains available if Gemini or Razorpay is unavailable.
