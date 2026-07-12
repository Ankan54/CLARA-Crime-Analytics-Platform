export interface DemoUser {
  employeeId: number;
  kgid: string;
  name: string;
  rank: string;
  station: string;
}

export const FIXED_DEMO_USER: DemoUser = {
  employeeId: 5007,
  kgid: "KG006001",
  name: "Deepa Kamath",
  rank: "PSI",
  station: "Cyber Crime PS, Bengaluru City",
};
