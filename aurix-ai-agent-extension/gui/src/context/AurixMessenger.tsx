/**
 * AurixMessenger — GUI-side bridge to the AURIX extension host.
 *
 * Follows the same pattern as Continue's IdeMessenger:
 *   post()          — fire-and-forget
 *   request()       — request-response (Promise)
 *   streamRequest() — streaming (AsyncGenerator)
 *
 * Communication uses window.postMessage / vscode.postMessage.
 */

import { createContext } from "react";
import { v4 as uuidv4 } from "uuid";

interface VsCodeApi {
  postMessage(msg: unknown): void;
}

declare const vscode: VsCodeApi;

export interface Message {
  messageType: string;
  messageId: string;
  data: any;
}

export interface IAurixMessenger {
  post(messageType: string, data?: any, messageId?: string): void;
  request<T = any>(messageType: string, data?: any): Promise<T>;
  streamRequest(
    messageType: string,
    data?: any,
    cancelToken?: AbortSignal,
  ): AsyncGenerator<any[], any>;
  streamChat(
    userText: string,
    cancelToken?: AbortSignal,
    history?: Array<{ role: string; content: string }>,
  ): AsyncGenerator<string[], void>;
}

export class AurixMessenger implements IAurixMessenger {
  private _post(messageType: string, data: any, messageId: string = uuidv4()) {
    if (typeof vscode === "undefined") {
      console.warn("[AurixMessenger] vscode API unavailable");
      return;
    }
    vscode.postMessage({ messageType, messageId, data } as Message);
  }

  post(messageType: string, data?: any, messageId?: string) {
    this._post(messageType, data ?? undefined, messageId ?? uuidv4());
  }

  request<T = any>(messageType: string, data?: any): Promise<T> {
    const messageId = uuidv4();
    return new Promise<T>((resolve) => {
      const handler = (event: MessageEvent<Message>) => {
        if (event.data.messageId === messageId) {
          window.removeEventListener("message", handler);
          const res = event.data.data;
          resolve(res?.content ?? res);
        }
      };
      window.addEventListener("message", handler);
      this._post(messageType, data, messageId);
    });
  }

  async *streamRequest(
    messageType: string,
    data?: any,
    cancelToken?: AbortSignal,
  ): AsyncGenerator<any[], any> {
    const messageId = uuidv4();
    this._post(messageType, data, messageId);

    const buffer: any[] = [];
    let index = 0;
    let done = false;
    let returnVal: any = undefined;
    let error: string | null = null;

    const handler = (event: MessageEvent<Message>) => {
      if (event.data.messageId === messageId) {
        const d = event.data.data;
        if (d?.error) {
          error = d.error;
          return;
        }
        if (d?.done) {
          window.removeEventListener("message", handler);
          done = true;
          returnVal = d.content;
        } else {
          buffer.push(d?.content ?? d);
        }
      }
    };
    window.addEventListener("message", handler);

    const handleAbort = () => {
      this._post("abort", undefined, messageId);
    };
    cancelToken?.addEventListener("abort", handleAbort);

    try {
      while (!done) {
        if (error) { throw new Error(error); }
        if (buffer.length > index) {
          const chunks = buffer.slice(index);
          index = buffer.length;
          yield chunks;
        }
        await new Promise((r) => setTimeout(r, 50));
      }
      if (buffer.length > index) {
        yield buffer.slice(index);
      }
      return returnVal;
    } finally {
      cancelToken?.removeEventListener("abort", handleAbort);
    }
  }

  async *streamChat(
    userText: string,
    cancelToken?: AbortSignal,
    history?: Array<{ role: string; content: string }>,
  ): AsyncGenerator<string[], void> {
    // Build messages array: include conversation history + current user message
    const messages = [
      ...(history ?? []).map((m) => ({ role: m.role, content: m.content })),
      { role: "user", content: userText },
    ];
    const gen = this.streamRequest(
      "llm/streamChat",
      {
        messages,
      },
      cancelToken,
    );
    for await (const chunks of gen) {
      // Each chunk is an array of ChatMessage objects
      yield chunks.map((c: any) => {
        if (typeof c === "string") { return c; }
        if (Array.isArray(c)) { return c.map((m: any) => m?.content ?? "").join(""); }
        return c?.content ?? "";
      });
    }
  }
}

export const MessengerContext = createContext<IAurixMessenger>(
  new AurixMessenger(),
);
