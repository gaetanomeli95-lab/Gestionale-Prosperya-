-- PostgreSQL defence-in-depth blueprint (Phase 5 hardening) — NOT applied by Alembic yet.
-- Adapted from the abandoned prototype's 0001_security.sql to the tenant_id model.
-- Goals: (1) runtime role that does not own tables and cannot bypass RLS;
--        (2) RLS on every tenant-owned table keyed on app.tenant_id;
--        (3) DB-level append-only guards mirroring the ORM listeners (ADR-014).
-- Application sets `SET LOCAL app.user_id = ...; SET LOCAL app.tenant_id = ...` per transaction.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prosperya_app') THEN
        CREATE ROLE prosperya_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prosperya_app'
               AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls)) THEN
        RAISE EXCEPTION 'prosperya_app has unsafe privileges';
    END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO prosperya_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO prosperya_app;
-- Append-only history: no UPDATE/DELETE grants at all.
REVOKE UPDATE, DELETE ON audit_log, import_batches, actuals, budget_versions,
    invoice_transmission_events, webhook_events FROM prosperya_app;

CREATE OR REPLACE FUNCTION public.app_tenant_id() RETURNS UUID
LANGUAGE SQL STABLE PARALLEL SAFE SET search_path = pg_catalog, public
AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

-- Enable + force RLS on every table that carries tenant_id.
DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'tenant_id'
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON public.%I TO prosperya_app '
            'USING (tenant_id = public.app_tenant_id()) '
            'WITH CHECK (tenant_id = public.app_tenant_id())', t);
    END LOOP;
END $$;

-- users.tenant_id is nullable for staff: staff rows must remain readable for auth.
DROP POLICY IF EXISTS tenant_isolation ON public.users;
CREATE POLICY users_visible ON public.users TO prosperya_app
    USING (tenant_id IS NULL OR tenant_id = public.app_tenant_id());

CREATE OR REPLACE FUNCTION public.reject_history_mutation() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public
AS $$ BEGIN RAISE EXCEPTION 'Append-only history cannot be updated or deleted' USING ERRCODE = '42501'; END $$;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['audit_log', 'import_batches', 'actuals', 'budget_versions',
                             'invoice_transmission_events', 'webhook_events'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS append_only_guard ON public.%I', t);
        EXECUTE format('CREATE TRIGGER append_only_guard BEFORE UPDATE OR DELETE ON public.%I '
                       'FOR EACH ROW EXECUTE FUNCTION public.reject_history_mutation()', t);
    END LOOP;
END $$;
