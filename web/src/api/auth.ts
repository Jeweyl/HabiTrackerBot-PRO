import { apiRequest } from "./client"

export type TokenExchangeResponse = {
  access_token: string
  token_type: string
  expires_in: number
}

export async function exchangeToken(
  token: string,
  signal?: AbortSignal,
): Promise<TokenExchangeResponse> {
  return apiRequest<TokenExchangeResponse>("/api/v1/auth/exchange", {
    method: "POST",
    body: { token },
    auth: false,
    signal,
  })
}
