# coding=utf-8
# Copyright 2016 Foursquare Labs Inc. All Rights Reserved.

from __future__ import (
  absolute_import,
  division,
  generators,
  nested_scopes,
  print_function,
  unicode_literals,
  with_statement,
)

import os.path
from textwrap import dedent

from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.resources import Resources as BaseResources
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdir

from pants.contrib.webpack.targets.webpack_module import WebPackModule


class WebPack(NodeTask, SimpleCodegenTask):
  """Run webpack on WebPackModule targets.

  The result is a synthetic target that subclasses `Resources` and
  the task exports the `compile_classpath` product, so
  the output should appear on the classpath of any
  JVM target that transitively depends on the node target
  being codegenned.

  WARNING: The node module must express a dependency on webpack
  in its package.json / npm-shrinkwrap.json, or this task will
  fail.
  """

  class Resources(BaseResources):
    """Resources container to hold generated json."""

  @classmethod
  def product_types(cls):
    return [WebPack.Resources, 'compile_classpath']

  @property
  def cache_target_dirs(self):
    return True

  @property
  def _copy_target_attributes(self):
    # Override from SimpleCodegenTask, which expects targets to have a 'provided' attribute.
    # NOTE(Mateo): This is needed for compatability with Pants 1.1.0.
    return ['tags', 'scope']

  @classmethod
  def implementation_version(cls):
    return super(WebPack, cls).implementation_version() + [('WebPack', 3)]

  @classmethod
  def prepare(cls, options, round_manager):
    super(WebPack, cls).prepare(options, round_manager)
    round_manager.require_data(NodePaths)

  def synthetic_target_type(self, target):
    return WebPack.Resources

  def is_gentarget(self, target):
    return isinstance(target, WebPackModule)

  def execute_codegen(self, target, target_workdir):
    node_paths = self.context.products.get_data(NodePaths)
    if not node_paths:
      raise TaskError("No npm distribution was found!")
    node_path = node_paths.node_path(target)
    dest_dir = os.path.join(target_workdir, 'webpack')
    safe_mkdir(target_workdir, clean=True)

    # Added "bail" to the args since webpack only returns failure on failed transpiling, treating missing deps or
    # syntax errors as soft errors. This resulted in Pants returning success while the canary fails health check.
    args = [
      'run-script',
      'webpack',
      '--',
      '--bail',
      '--output-path={}'.format(dest_dir),
      '--env=dist',
    ]
    with pushd(node_path):
      result, npm_run = self.execute_npm(
        args=args,
        workunit_labels=[WorkUnitLabel.RUN],
      )
      if result:
        raise TaskError(dedent(
          """ webpack command:
          \n\t{} failed with exit code {}
          """
         .format(' '.join(npm_run.cmd), result)
        ))
