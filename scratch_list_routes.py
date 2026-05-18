import os
import ast
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def list_routes() -> None:
    """
    Parses files in app/api/routers to extract and log FastAPI route information.
    """
    routers_dir = 'app/api/routers'
    for file in sorted(os.listdir(routers_dir)):
            if not file.endswith('.py') or file == '__init__.py':
                continue
            logger.info("\n--- File: %s ---", file)
            path = os.path.join(routers_dir, file)
            with open(path, 'r', encoding='utf-8') as f:
                node = ast.parse(f.read())

            for body_node in node.body:
                if isinstance(body_node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    for decorator in body_node.decorator_list:
                        # check if decorator is a call to router.xxx
                        is_router = False
                        method = ""
                        url_path = ""
                        if isinstance(decorator, ast.Call):
                            func = decorator.func
                            if isinstance(func, ast.Attribute):
                                if isinstance(func.value, ast.Name) and func.value.id == 'router':
                                    is_router = True
                                    method = func.attr.upper()
                                    if decorator.args:
                                        arg = decorator.args[0]
                                        if isinstance(arg, ast.Constant):
                                            url_path = arg.value
                        if is_router:
                            logger.info("  %s %s -> %s", method, url_path, body_node.name)
if __name__ == '__main__':
    list_routes()
