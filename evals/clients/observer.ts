import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "guidance-eval-observer",
  async setup(ctx) {
    const gateway = process.env.EVAL_GATEWAY
    const token = process.env.EVAL_GATE_TOKEN
    if (!gateway || !token) throw new Error("Evaluation recorder connection is missing")
    const send = async (event: unknown) => {
      const response = await fetch(`${gateway}/observe`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-eval-token": token },
        body: JSON.stringify(event),
      })
      if (!response.ok) throw new Error(`Evaluation recorder: ${response.status}`)
    }
    await ctx.tool.hook("execute.before", (event) => send({ event: "tool.before", ...event }))
    await ctx.tool.hook("execute.after", (event) => send({ event: "tool.after", ...event }))
    await ctx.shell.hook("create.before", (event) => send({ event: "shell", command: event.command,
      cwd: event.cwd, trace: event.env.GIT_TRACE2_EVENT }))
    await ctx.session.hook("title", (event) => { event.result = "Guidance evaluation" })
    await ctx.session.hook("context", async (event) => {
      await send({ event: "context", ...event, skills: await ctx.skill.list(), plugins: await ctx.plugin.list() })
    })
  },
})
