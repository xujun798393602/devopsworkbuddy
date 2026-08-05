export interface ProblemDetails { type:string; title:string; status:number; detail:string; error_code:string; trace_id:string }
export class ApiProblem extends Error { constructor(public readonly problem:ProblemDetails){super(problem.detail);this.name='ApiProblem'} }
