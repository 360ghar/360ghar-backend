-- Remove saved payment methods. The /payments routes are deleted (contract decision:
-- payments). Nothing else references payment_methods: no foreign key points to it,
-- and PM rent payments use rent_payments, not this table.

DROP TABLE IF EXISTS payment_methods;
