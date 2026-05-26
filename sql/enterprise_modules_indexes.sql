-- enterprise_modules_indexes.sql
-- Non-destructive, concurrent-safe index definitions for IVMS Maintenance, Drivers, and Site Operations.

CREATE INDEX IF NOT EXISTS idx_maint_sched_tenant ON maintenance_schedule(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_maint_hist_tenant ON maintenance_history(tenant_id);
CREATE INDEX IF NOT EXISTS idx_maint_attach_history ON maintenance_attachments(history_id);
CREATE INDEX IF NOT EXISTS idx_drivers_tenant ON drivers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_driver_attendance_tenant_date ON driver_attendance(tenant_id, date);
CREATE INDEX IF NOT EXISTS idx_driver_sessions_drv ON driver_sessions(driver_id);
CREATE INDEX IF NOT EXISTS idx_site_visits_tenant ON site_visits(tenant_id, arrival_time);
CREATE INDEX IF NOT EXISTS idx_service_tickets_tenant ON service_tickets(tenant_id, status);
