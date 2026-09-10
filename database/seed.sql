-- Synthetic patients used by the simulator and dashboard.
INSERT INTO patients (external_ref, display_name, ward_id) VALUES
    ('pat_10001', 'Synthetic Patient A', 'ward_icu_1'),
    ('pat_10002', 'Synthetic Patient B', 'ward_icu_1'),
    ('pat_10003', 'Synthetic Patient C', 'ward_med_2'),
    ('pat_10004', 'Synthetic Patient D', 'ward_med_2'),
    ('pat_10005', 'Synthetic Patient E', 'ward_step_3'),
    ('pat_10092', 'Synthetic Patient Demo', 'ward_icu_1')
ON CONFLICT (external_ref) DO NOTHING;
