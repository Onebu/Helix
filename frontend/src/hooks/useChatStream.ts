import { useState, useCallback, useRef, useEffect } from 'react'
import { getApiBaseUrl } from '@/lib/api-config'

export interface ToolCallData {
  id: string
  name: string
  arguments: Record<string, unknown>
}

export interface ToolResultData {
  tool_call_id: string
  name: string
  content: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  toolCall?: ToolCallData
  toolResult?: ToolResultData
  step?: number
}

export interface ChatUsage {
  input_tokens: number
  output_tokens: number
  cost_usd: number
  model: string
}

export interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  error: string | null
  totalCost: number
  turnCount: number
  limitReached: string | null
  usage: ChatUsage[]
}

const INITIAL_STATE: ChatState = {
  messages: [],
  isStreaming: false,
  error: null,
  totalCost: 0,
  turnCount: 0,
  limitReached: null,
  usage: [],
}

/**
 * Parse SSE events from a text buffer.
 * Returns [parsedEvents, remainingBuffer].
 * SSE format: lines starting with "event:" and "data:" separated by blank lines.
 */
function parseSSEBuffer(buffer: string): [Array<{ event: string; data: string }>, string] {
  const events: Array<{ event: string; data: string }> = []
  const blocks = buffer.split('\n\n')

  // The last block may be incomplete -- keep it in the buffer
  const remaining = blocks.pop() ?? ''

  for (const block of blocks) {
    if (!block.trim()) continue

    let event = ''
    let data = ''

    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        data = line.slice(5).trim()
      }
    }

    if (event && data) {
      events.push({ event, data })
    }
  }

  return [events, remaining]
}

export function useChatStream(promptId: string) {
  const [state, setState] = useState<ChatState>(INITIAL_STATE)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [])

  const sendMessage = useCallback(
    async (
      content: string,
      variables: Record<string, string>,
      turnLimit: number,
      costBudget: number,
    ) => {
      // Check cost budget client-side before sending
      if (state.totalCost >= costBudget && costBudget > 0) {
        setState((prev) => ({ ...prev, limitReached: 'cost_budget' }))
        return
      }

      // Abort any in-progress stream
      abortControllerRef.current?.abort()
      const controller = new AbortController()
      abortControllerRef.current = controller

      // Add user message and empty assistant message
      const userMessage: ChatMessage = { role: 'user', content }
      const assistantMessage: ChatMessage = { role: 'assistant', content: '' }

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage, assistantMessage],
        isStreaming: true,
        error: null,
      }))

      // Build conversation history (user + assistant messages only, not system)
      const allMessages = [...state.messages, userMessage].filter(
        (m) => m.role === 'user' || m.role === 'assistant',
      )

      const requestBody = {
        messages: allMessages.map((m) => ({ role: m.role, content: m.content })),
        variables,
        turn_limit: turnLimit,
        cost_budget: costBudget,
      }

      try {
        const response = await fetch(
          `${getApiBaseUrl()}/api/prompts/${promptId}/chat`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
            signal: controller.signal,
          },
        )

        if (!response.ok) {
          const errorText = await response.text()
          setState((prev) => ({
            ...prev,
            isStreaming: false,
            error: `Request failed (${response.status}): ${errorText}`,
          }))
          return
        }

        const reader = response.body?.getReader()
        if (!reader) {
          setState((prev) => ({
            ...prev,
            isStreaming: false,
            error: 'No response body stream available',
          }))
          return
        }

        const decoder = new TextDecoder()
        let sseBuffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          sseBuffer += decoder.decode(value, { stream: true })
          const [events, remaining] = parseSSEBuffer(sseBuffer)
          sseBuffer = remaining

          for (const evt of events) {
            let parsed: Record<string, unknown>
            try {
              parsed = JSON.parse(evt.data) as Record<string, unknown>
            } catch {
              continue
            }

            switch (evt.event) {
              case 'token': {
                const tokenContent = parsed.content as string
                const tokenStep = parsed.step as number | undefined
                setState((prev) => {
                  const msgs = [...prev.messages]
                  const last = msgs[msgs.length - 1]
                  if (last && last.role === 'assistant' && last.step === tokenStep) {
                    msgs[msgs.length - 1] = {
                      ...last,
                      content: last.content + tokenContent,
                    }
                  } else {
                    msgs.push({ role: 'assistant', content: tokenContent, step: tokenStep })
                  }
                  return { ...prev, messages: msgs }
                })
                break
              }

              case 'tool_call': {
                const toolCall: ToolCallData = {
                  id: parsed.id as string,
                  name: parsed.name as string,
                  arguments: parsed.arguments as Record<string, unknown>,
                }
                setState((prev) => ({
                  ...prev,
                  messages: [
                    ...prev.messages,
                    {
                      role: 'tool_call' as const,
                      content: toolCall.name,
                      toolCall,
                      step: parsed.step as number | undefined,
                    },
                  ],
                }))
                break
              }

              case 'tool_result': {
                const toolResult: ToolResultData = {
                  tool_call_id: parsed.tool_call_id as string,
                  name: parsed.name as string,
                  content: parsed.content as string,
                }
                setState((prev) => ({
                  ...prev,
                  messages: [
                    ...prev.messages,
                    {
                      role: 'tool_result' as const,
                      content: toolResult.content,
                      toolResult,
                      step: parsed.step as number | undefined,
                    },
                  ],
                }))
                break
              }

              case 'done': {
                const usageEntry: ChatUsage = {
                  input_tokens: parsed.input_tokens as number,
                  output_tokens: parsed.output_tokens as number,
                  cost_usd: parsed.cost_usd as number,
                  model: parsed.model as string,
                }
                setState((prev) => {
                  const newTotalCost = prev.totalCost + usageEntry.cost_usd
                  const newTurnCount = prev.turnCount + 1
                  // Proactively check limits after this turn completes
                  let newLimitReached = prev.limitReached
                  if (!newLimitReached && costBudget > 0 && newTotalCost >= costBudget) {
                    newLimitReached = 'cost_budget'
                  }
                  if (!newLimitReached && newTurnCount >= turnLimit) {
                    newLimitReached = 'turn_limit'
                  }
                  return {
                    ...prev,
                    isStreaming: false,
                    usage: [...prev.usage, usageEntry],
                    totalCost: newTotalCost,
                    turnCount: newTurnCount,
                    limitReached: newLimitReached,
                  }
                })
                break
              }

              case 'error': {
                setState((prev) => ({
                  ...prev,
                  isStreaming: false,
                  error: parsed.message as string,
                }))
                break
              }

              case 'limit_reached': {
                setState((prev) => ({
                  ...prev,
                  isStreaming: false,
                  limitReached: parsed.reason as string,
                }))
                break
              }
            }
          }
        }

        // Handle any remaining buffered events after stream ends
        if (sseBuffer.trim()) {
          const [finalEvents] = parseSSEBuffer(sseBuffer + '\n\n')
          for (const evt of finalEvents) {
            if (evt.event === 'done') {
              let parsed: Record<string, unknown>
              try {
                parsed = JSON.parse(evt.data) as Record<string, unknown>
              } catch {
                continue
              }
              const usageEntry: ChatUsage = {
                input_tokens: parsed.input_tokens as number,
                output_tokens: parsed.output_tokens as number,
                cost_usd: parsed.cost_usd as number,
                model: parsed.model as string,
              }
              setState((prev) => {
                const newTotalCost = prev.totalCost + usageEntry.cost_usd
                const newTurnCount = prev.turnCount + 1
                let newLimitReached = prev.limitReached
                if (!newLimitReached && costBudget > 0 && newTotalCost >= costBudget) {
                  newLimitReached = 'cost_budget'
                }
                if (!newLimitReached && newTurnCount >= turnLimit) {
                  newLimitReached = 'turn_limit'
                }
                return {
                  ...prev,
                  isStreaming: false,
                  usage: [...prev.usage, usageEntry],
                  totalCost: newTotalCost,
                  turnCount: newTurnCount,
                  limitReached: newLimitReached,
                }
              })
            }
          }
        }

        // Ensure streaming is marked as done even if no done event received
        setState((prev) => (prev.isStreaming ? { ...prev, isStreaming: false } : prev))
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // User-initiated abort, not an error
          setState((prev) => ({ ...prev, isStreaming: false }))
          return
        }
        setState((prev) => ({
          ...prev,
          isStreaming: false,
          error: err instanceof Error ? err.message : 'Unknown error occurred',
        }))
      }
    },
    [promptId, state.messages, state.totalCost],
  )

  const reset = useCallback(() => {
    abortControllerRef.current?.abort()
    setState(INITIAL_STATE)
  }, [])

  return {
    ...state,
    sendMessage,
    reset,
  }
}
