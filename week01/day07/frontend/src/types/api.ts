export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export interface PageResult<T = unknown> {
  code: number;
  message: string;
  data: T[];
  total: number;
  page: number;
  pageSize: number;
}
