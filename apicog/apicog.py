import inspect
import ssl

from redbot.core import commands, Config
from aiohttp import web
from redbot.core.utils.chat_formatting import box


class APICog(commands.Cog):
    def __init__(self, bot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot

        self.config = Config.get_conf(self, identifier=3260)
        self.config.register_global(port=80, certfile=None, keyfile=None)
        self.config.init_custom("Endpoint", 1)
        self.config.register_custom("Endpoint", cog=None, function_name=None)

        self.site = None
        self.runner = None

    async def cog_load(self):
        app = web.Application()

        # 2. Add your routes
        app.router.add_get('/', self.root_handler)
        app.router.add_get('/{endpoint_name}', self.dynamic_handler)

        ssl_context = None
        if await self.config.certfile() is not None:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(
                certfile=await self.config.certfile(),
                keyfile=await self.config.keyfile()
            )

        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()

        self.site = web.TCPSite(
            self.runner,
            '0.0.0.0',
            await self.config.port(),
            ssl_context=ssl_context
        )
        await self.site.start()

    async def cog_unload(self):
        if self.site is not None:
            await self.site.stop()
        if self.runner is not None:
            await self.runner.cleanup()

    async def root_handler(self, request):
        return web.Response(text=f"Maybe put something here eventually...")

    async def dynamic_handler(self, request):
        endpoint_name = request.match_info['endpoint_name']

        if (cog_name := await self.config.custom("Endpoint", endpoint_name).cog()) is None:
            return web.Response(text="Invalid endpoint.", status=404)
        if (cog := self.bot.get_cog(cog_name)) is None:
            return web.Response(text=f"Cog {cog} is not loaded.", status=404)
        function_name = await self.config.custom("Endpoint", endpoint_name).function_name()
        if (function := getattr(cog, function_name, None)) is None:
            return web.Response(text=f"Function {function_name} does not exist.  Contact an administrator.", status=503)

        qps = request.query.copy()

        for name, param in inspect.signature(function).parameters.items():
            if name not in qps:
                if param.default is not inspect.Parameter.empty:
                    continue
                return web.Response(text=f"Parameter '{name}' is required.", status=400)
            if param.annotation is not inspect.Parameter.empty:
                try:
                    qps[name] = param.annotation(qps[name])
                except ValueError:
                    return web.Response(text=f"Parameter '{name}' must be a(n) {param.annotation.__name__}.",
                                        status=400)

        status = 200

        try:
            response = function(**qps)
            if inspect.isawaitable(response):
                response = await response
        except Exception as e:
            return web.Response(text=str(e), status=400)

        if isinstance(response, dict):
            if 'response' in response:
                status = response.get('status', 200)
                response = response['response']

        if isinstance(response, str):
            return web.Response(text=response, status=status)
        elif isinstance(response, dict):
            return web.json_response(response, status=status)

    @commands.group()
    async def api(self, ctx):
        """Manage the API"""
        ...

    @api.command()
    @commands.is_owner()
    async def remove(self, ctx, endpoint: str):
        """Remove a endpoint"""
        await self.config.custom("Endpoint", endpoint).clear()
        await ctx.tick()

    @api.command()
    async def list(self, ctx):
        """List all endpoints"""
        data = [f"/{endpoint}: {info['cog']}.{info['function_name']}"
                for endpoint, info in (await self.config.custom("Endpoint").all()).items()]
        await ctx.send(box('\n'.join(data)))

    @api.command()
    async def info(self, ctx, endpoint: str):
        """Show info about an endpoint"""
        endpoint = endpoint.lstrip('/')
        if (cog_name := await self.config.custom("Endpoint", endpoint).cog()) is None:
            return await ctx.send("Endpoint not found.")
        if (cog := self.bot.get_cog(cog_name)) is None:
            return await ctx.send(f"Endpoint's cog ({cog_name}) not loaded.")
        function_name = await self.config.custom("Endpoint", endpoint).function_name()
        if (function := getattr(cog, function_name, None)) is None:
            return await ctx.send(f"Function {function_name} not found.  Contact an administrator.")

        data = f"Info for endpoint /{endpoint}\n\n"
        if function.__doc__ is not None:
            data += function.__doc__ + '\n\n'
        data += 'Parameters:\n'
        for name, param in inspect.signature(function).parameters.items():
            data += (f" {name}: {param.annotation.__name__ + ' ' if param.annotation else ''}"
                     f"{f'(default: {param.default})' if param.default is not inspect.Parameter.empty else ''}\n")
        await ctx.send(box(data))

    @api.group()
    @commands.is_owner()
    async def setup(self, ctx):
        ...

    @setup.command()
    async def setport(self, ctx, port: int):
        await self.config.port.set(port)
        await ctx.tick()

    @setup.command()
    async def setcertfile(self, ctx, certfile):
        await self.config.certfile.set(certfile)
        await ctx.tick()

    @setup.command()
    async def setkeyfile(self, ctx, keyfile):
        await self.config.keyfile.set(keyfile)
        await ctx.tick()

    async def add_endpoint(self, endpoint_name, cog_name, function_name):
        await self.config.custom("Endpoint", endpoint_name).cog.set(cog_name)
        await self.config.custom("Endpoint", endpoint_name).function_name.set(function_name)

    async def remove_endpoint(self, endpoint_name):
        await self.config.custom("Endpoint", endpoint_name).cog.clear()
