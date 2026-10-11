// 3システムが共有するマスタ: 担当者・顧客・車両・工程・作業。
import { DataValidationError, requireDecimal, requireText } from "../errors";
import { queryOne, queryRows, transaction, type Database, type Queryable } from "../queryable";
import type { DecimalInput, DecimalString, JsonObject } from "../types";

export type Staff = { staffCode: string; displayName: string; isSimulator: boolean };

export async function upsertStaff(db: Queryable, staff: Staff): Promise<void> {
  await db.query(
    `INSERT INTO staff (staff_code, display_name, is_simulator) VALUES ($1, $2, $3)
     ON CONFLICT (staff_code) DO UPDATE SET display_name = EXCLUDED.display_name`,
    [requireText(staff.staffCode, "staff_code"), requireText(staff.displayName, "display_name"), staff.isSimulator],
  );
}

export async function ensureCustomer(db: Queryable, customerRef: string, isSimulator = false): Promise<void> {
  await db.query(
    "INSERT INTO customers (customer_ref, is_simulator) VALUES ($1, $2) ON CONFLICT (customer_ref) DO NOTHING",
    [requireText(customerRef, "customer_ref"), isSimulator],
  );
}

export type VehicleInput = {
  vehicleRef: string;
  modelCode?: string | null;
  /** 初度登録年月 "YYYY-MM"。和暦は呼び出し側で西暦に直してから渡す。 */
  firstRegisteredMonth?: string | null;
  modelName?: string | null;
  drive?: string | null;
  bodyClass?: string | null;
  attributes?: JsonObject;
  isSimulator?: boolean;
};

export type Vehicle = Required<Omit<VehicleInput, "attributes" | "isSimulator">> & {
  vehicleKey: string | null;
  attributes: JsonObject;
  isSimulator: boolean;
};

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

export function monthToDate(month: string, field: string): string {
  if (!MONTH_PATTERN.test(month)) {
    throw new DataValidationError(`${field}: YYYY-MM 形式で入力してください`);
  }
  return `${month}-01`;
}

const VEHICLE_COLUMNS = `
  vehicle_ref AS "vehicleRef", model_code AS "modelCode",
  to_char(first_registered_month, 'YYYY-MM') AS "firstRegisteredMonth",
  vehicle_key AS "vehicleKey", model_name AS "modelName", drive, body_class AS "bodyClass",
  attributes, is_simulator AS "isSimulator"`;

export async function upsertVehicle(db: Queryable, vehicle: VehicleInput): Promise<Vehicle> {
  const month = vehicle.firstRegisteredMonth
    ? monthToDate(vehicle.firstRegisteredMonth, "first_registered_month")
    : null;
  const row = await queryOne<Vehicle>(
    db,
    `INSERT INTO vehicles (vehicle_ref, model_code, first_registered_month, model_name, drive, body_class, attributes, is_simulator)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     ON CONFLICT (vehicle_ref) DO UPDATE SET
       model_code = EXCLUDED.model_code, first_registered_month = EXCLUDED.first_registered_month,
       model_name = EXCLUDED.model_name, drive = EXCLUDED.drive, body_class = EXCLUDED.body_class,
       attributes = EXCLUDED.attributes
     RETURNING ${VEHICLE_COLUMNS}`,
    [
      requireText(vehicle.vehicleRef, "vehicle_ref"),
      vehicle.modelCode ?? null,
      month,
      vehicle.modelName ?? null,
      vehicle.drive ?? null,
      vehicle.bodyClass ?? null,
      vehicle.attributes ?? {},
      vehicle.isSimulator ?? false,
    ],
  );
  return row!;
}

export async function getVehicle(db: Queryable, vehicleRef: string): Promise<Vehicle | undefined> {
  return queryOne<Vehicle>(db, `SELECT ${VEHICLE_COLUMNS} FROM vehicles WHERE vehicle_ref = $1`, [vehicleRef]);
}

export type Operation = { operationCode: string; name: string; perUnit: string | null };

export async function upsertOperation(db: Queryable, operation: Operation): Promise<void> {
  await db.query(
    `INSERT INTO operations (operation_code, name, per_unit) VALUES ($1, $2, $3)
     ON CONFLICT (operation_code) DO UPDATE SET name = EXCLUDED.name, per_unit = COALESCE(EXCLUDED.per_unit, operations.per_unit)`,
    [requireText(operation.operationCode, "operation_code"), requireText(operation.name, "name"), operation.perUnit],
  );
}

export type JobOperation = { operationCode: string; hours: DecimalString; shared: boolean };
export type JobOperationInput = { operationCode: string; hours: DecimalInput; shared?: boolean };

export type JobInput = {
  jobCode: string;
  name: string;
  baseLaborHours?: DecimalInput | null;
  basisUnit?: string | null;
  basisSource?: string | null;
  catalogVersion?: string | null;
  workAreas?: string[];
  attributes?: JsonObject;
  operations?: JobOperationInput[];
  isSimulator?: boolean;
};

export type Job = {
  jobCode: string;
  name: string;
  baseLaborHours: DecimalString | null;
  basisUnit: string | null;
  basisSource: string | null;
  catalogVersion: string | null;
  workAreas: string[];
  attributes: JsonObject;
  isSimulator: boolean;
  operations: JobOperation[];
};

/** 作業と含まれる工程をまとめて登録する。工程の並びは渡した順で置き換える。 */
export async function upsertJob(db: Database, job: JobInput): Promise<void> {
  const jobCode = requireText(job.jobCode, "job_code");
  const baseHours = job.baseLaborHours == null ? null : requireDecimal(job.baseLaborHours, "base_labor_hours");
  await transaction(db, async (tx) => {
    await tx.query(
      `INSERT INTO jobs (job_code, name, base_labor_hours, basis_unit, basis_source, catalog_version, work_areas, attributes, is_simulator)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       ON CONFLICT (job_code) DO UPDATE SET
         name = EXCLUDED.name, base_labor_hours = EXCLUDED.base_labor_hours, basis_unit = EXCLUDED.basis_unit,
         basis_source = EXCLUDED.basis_source, catalog_version = EXCLUDED.catalog_version,
         work_areas = EXCLUDED.work_areas, attributes = EXCLUDED.attributes`,
      [
        jobCode,
        requireText(job.name, "name"),
        baseHours,
        job.basisUnit ?? null,
        job.basisSource ?? null,
        job.catalogVersion ?? null,
        job.workAreas ?? [],
        job.attributes ?? {},
        job.isSimulator ?? false,
      ],
    );
    if (job.operations) {
      await tx.query("DELETE FROM job_operations WHERE job_code = $1", [jobCode]);
      for (const [index, operation] of job.operations.entries()) {
        await tx.query(
          "INSERT INTO job_operations (job_code, operation_code, position, hours, shared) VALUES ($1, $2, $3, $4, $5)",
          [
            jobCode,
            requireText(operation.operationCode, "operation_code"),
            index + 1,
            requireDecimal(operation.hours, "hours"),
            operation.shared ?? false,
          ],
        );
      }
    }
  });
}

const JOB_SELECT = `
  SELECT j.job_code AS "jobCode", j.name, j.base_labor_hours::text AS "baseLaborHours",
         j.basis_unit AS "basisUnit", j.basis_source AS "basisSource", j.catalog_version AS "catalogVersion",
         j.work_areas AS "workAreas", j.attributes, j.is_simulator AS "isSimulator",
         COALESCE(
           (SELECT json_agg(json_build_object('operationCode', o.operation_code, 'hours', o.hours::text, 'shared', o.shared)
                            ORDER BY o.position)
              FROM job_operations o WHERE o.job_code = j.job_code),
           '[]'
         ) AS operations
    FROM jobs j`;

export async function getJob(db: Queryable, jobCode: string): Promise<Job | undefined> {
  return queryOne<Job>(db, `${JOB_SELECT} WHERE j.job_code = $1`, [jobCode]);
}

export async function listJobs(db: Queryable, query = ""): Promise<Job[]> {
  // LIKE だと入力の % や _ がワイルドカードになるので、部分一致は strpos で見る。
  return queryRows<Job>(
    db,
    `${JOB_SELECT} WHERE strpos(lower(j.name), lower($1)) > 0 OR strpos(lower(j.job_code), lower($1)) > 0 ORDER BY j.job_code`,
    [query.trim()],
  );
}
