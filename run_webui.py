#!/usr/bin/python3

import sys
import atexit
import asyncio
from absl import flags, app
import gradio as gr
from gradio.routes import mount_gradio_app
import uvicorn
from fastapi import FastAPI, Depends, Form, HTTPException, status, Request
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.agent.mcp import MCPAgent
from app.config import config
from app.logger import logger

FLAGS = flags.FLAGS

def add_options():
  flags.DEFINE_string('host', default = '0.0.0.0', help = 'service host')
  flags.DEFINE_integer('port', default = 8081, help = 'service port')
  flags.DEFINE_enum('conn_type', default = 'stdio', enum_values = {'stdio', 'sse'}, help = 'connection type: stdio or sse')
  flags.DEFINE_string('mcp_host', default = 'http://127.0.0.1:8000/sse', help = 'url to mcp service')

class Runner(object):
  def __init__(self, conn_type, mcp_host):
    self.agent = MCPAgent()
    if conn_type == 'stdio':
      asyncio.run(self.agent.initialize(
        connection_type = "stdio",
        command = sys.executable,
        args = ['-m', config.mcp_config.server_reference]
      ))
    else:
      asyncio.run(self.agent.initialize(
        connection_type = "sse",
        server_url = mcp_host,
      ))
    atexit.register(self.__del__)
  def __del__(self,):
    asyncio.run(self.agent.cleanup())
  def __call__(self, question):
    return asyncio.run(self.agent.run(question))

def create_interface():
  # 1) open manus agent
  runner = Runner(FLAGS.conn_type, FLAGS.mcp_host)
  # 2) callback functions
  def chatbot_response(user_input, history):
    history.append({'role': 'user', 'content': user_input})
    yield history
    response = runner(user_input)
    history.append({'role': 'assistant', 'content': response})
    yield history
  # 3) GUI definition
  with gr.Blocks() as demo:
    with gr.Column():
      with gr.Row(equal_height = True):
        gr.Markdown("# Open Manus")
      with gr.Row(equal_height = True):
        user_input = gr.Textbox(label = "question?", scale = 5)
        submit_btn = gr.Button("submit", scale = 1)
      with gr.Row():
        chatbot = gr.Chatbot(height = 450)
    submit_btn.click(chatbot_response, inputs = [user_input, chatbot], outputs = [chatbot], concurrency_limit = 64)
  return demo

application = FastAPI()

def main(unused_argv):
  global application
  demo = create_interface()
  application = mount_gradio_app(app = application, blocks = demo, path = '/')
  uvicorn.run(
    application,
    host = FLAGS.host,
    port = FLAGS.port
  )

if __name__ == "__main__":
  add_options()
  app.run(main)
