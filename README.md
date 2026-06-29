# DyerGate

DyerGate is a fully reconstructed 11-phase enterprise LLM gateway platform.

## Getting Started (Windows)

1. **Start Docker Desktop**: Ensure Docker is running in the background.
2. **Run the application**: Double-click `run.bat` or execute `.\run.bat` from powershell.
3. **Access the application**: 
   - API: `http://localhost:8080`
   - Analytics Dashboard: `http://localhost:8080/analytics`
   - Studio UI: `http://localhost:8080/studio`

## Deployment

To deploy this in production and earn revenue at no upfront cost:
1. Push this codebase to a private GitHub repository.
2. Link the repository to a free PaaS provider (e.g., Render, Railway, or Fly.io).
3. The platform uses Docker natively, meaning the `Dockerfile` will automatically be detected and built by any of these providers.
4. Set the environment variables shown in `.env.example` in the provider's dashboard.
5. The SQLite database is built to scale initially, but you should configure the `DATABASE_URL` to point to a free managed PostgreSQL database (e.g., Supabase) before inviting real paying users.
