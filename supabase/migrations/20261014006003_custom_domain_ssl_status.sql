-- ssl_status values are none, pending, active, failed (CustomDomainSSLStatus).
-- The service wrote "provisioning", which the enum does not define. Rows that
-- hold it are set to "pending", the state the service now writes.

UPDATE custom_domains SET ssl_status = 'pending' WHERE ssl_status = 'provisioning';
