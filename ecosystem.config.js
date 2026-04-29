module.exports = {
  apps: [
    {
      name: "baba-node-api",
      script: "gateway.py",
      interpreter: "python3",
      cwd: __dirname,
      max_memory_restart: "512M",
      autorestart: true,
    },
    {
      name: "baba-mcp-http",
      script: "-m",
      args: "baba_mcp.server",
      interpreter: "python3",
      cwd: __dirname,
      env: {
        MCP_TRANSPORT: "http",
        MCP_HTTP_HOST: "127.0.0.1",
        MCP_HTTP_PORT: "7000",
        BABA_GATEWAY_URL: "http://127.0.0.1:5000",
      },
      max_memory_restart: "256M",
      autorestart: true,
    },
  ],
};
