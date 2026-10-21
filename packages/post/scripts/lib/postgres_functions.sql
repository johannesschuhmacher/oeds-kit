-- SPDX-FileCopyrightText: Johannes Schuhmacher, Andre Meyer

-- SPDX-License-Identifier: AGPL-3.0-or-later

-- linear_interpolate function
CREATE OR REPLACE FUNCTION public.linear_interpolate(
    start_time TIMESTAMP,
    start_value NUMERIC,
    end_time TIMESTAMP,
    end_value NUMERIC,
    resolution INTERVAL DEFAULT '15 minutes'
) RETURNS TABLE(
    timestmp TIMESTAMP,
    interpolated_value NUMERIC
) AS $$
DECLARE
    count_missing_values INT;
BEGIN
    IF start_time >= end_time THEN
        RETURN;
    END IF;

    -- find the number of missing values
    count_missing_values := EXTRACT(EPOCH FROM (end_time - start_time)) / EXTRACT (EPOCH FROM resolution);

    FOR i in 1..count_missing_values-1 LOOP -- start at 1 to avoid the start_time and -1 to avoid the end_time
        timestmp := start_time + (i * resolution);
        interpolated_value := start_value + (end_value - start_value) * i / count_missing_values;
        RETURN NEXT;
    END LOOP;
END;
$$
LANGUAGE plpgsql;
