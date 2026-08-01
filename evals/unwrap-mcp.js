/**
 * Promote the MCP tool's JSON payload to Promptfoo `output`.
 *
 * The MCP provider surfaces content blocks:
 *   [{"type":"text","text":"{\"rows\":[...]}"}]
 * Assertions in evals/mcp.yaml operate on the inner payload.
 */
module.exports = (result, content) => {
  const fromResult = result?.content?.[0]?.text;
  if (typeof fromResult === "string" && fromResult.length > 0) {
    return fromResult;
  }

  if (typeof content === "string") {
    try {
      const parsed = JSON.parse(content);
      if (Array.isArray(parsed) && typeof parsed[0]?.text === "string") {
        return parsed[0].text;
      }
      if (typeof parsed?.content?.[0]?.text === "string") {
        return parsed.content[0].text;
      }
    } catch {
      /* content is already the tool payload */
    }
    return content;
  }

  if (Array.isArray(content) && typeof content[0]?.text === "string") {
    return content[0].text;
  }

  return typeof content === "string" ? content : JSON.stringify(content);
};
