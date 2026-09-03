module.exports = {
  apps: [
    {
      name: "mexc-momentum-scanner",
      script: "python",
      args: "-m src.main",
      cwd: "./",
      interpreter: "none",
      restart_delay: 5000,
      max_restarts: 50,
      autorestart: true,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
