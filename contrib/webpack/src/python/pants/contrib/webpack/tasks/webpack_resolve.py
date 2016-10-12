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

import hashlib
import logging
import os

from pants.base.build_environment import get_buildroot
from pants.base.fingerprint_strategy import TaskIdentityFingerprintStrategy
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_resolve import NodeResolve
from pants.util.dirutil import safe_mkdir

from pants.contrib.webpack.subsystems.resolvers.webpack_resolver import WebPackResolver
from pants.contrib.webpack.targets.webpack_module import WebPackModule


logger = logging.getLogger(__name__)


class WebPackResolveFingerprintStrategy(TaskIdentityFingerprintStrategy):

  def compute_fingerprint(self, target):
    super_fingerprint = super(WebPackResolveFingerprintStrategy, self).compute_fingerprint(target)
    if not isinstance(target, WebPackModule):
      return super_fingerprint
    hasher = hashlib.sha1()
    hasher.update(super_fingerprint)
    hasher.update(target.npm_json)
    with open(os.path.join(get_buildroot(), target.npm_json), 'rb') as f:
      hasher.update(f.read())
    return hasher.hexdigest()


class WebPackDistribution(Target):

   def __init__(self, distribution_fingerprint=None, *args, **kwargs):
    """Synthetic target that represents a resolved webpack distribution."""
    # Creating the synthetic target lets us avoid any special casing in regards to build order or cache invalidation.
    payload = Payload()
    payload.add_fields({
      'distribution_fingerprint': PrimitiveField(distribution_fingerprint),
    })
    super(WebPackDistribution, self).__init__(payload=payload, *args, **kwargs)


class WebPackResolve(NodeResolve):

  @classmethod
  def implementation_version(cls):
    return super(WebPackResolve, cls).implementation_version() + [('WebPackResolve', 2)]

  @classmethod
  def global_subsystems(cls):
    return super(WebPackResolve, cls).global_subsystems() + (WebPackResolver,)

  @classmethod
  def prepare(cls, options, round_manager):
    """Allow each resolver to declare additional product requirements."""
    WebPackResolver.prepare(options, round_manager)

  @classmethod
  def product_types(cls):
    return ['webpack_distribution']

  def cache_target_dirs(self):
    return True

  def execute(self):
    targets = self.context.targets(predicate=self._can_resolve_target)
    if not targets:
      return

    node_paths = self.context.products.get_data(NodePaths, init_func=NodePaths)

    invalidation_context = self.invalidated(
      targets,
      fingerprint_strategy=WebPackResolveFingerprintStrategy(self),
      topological_order=True,
      invalidate_dependents=True,
    )
    with invalidation_context as invalidation_check:
      webpack_distribution_target = self.create_synthetic_target(self.fingerprint)
      build_graph = self.context.build_graph
      for vt in invalidation_check.all_vts:
        resolver_for_target_type = self._resolver_for_target(vt.target).global_instance()
        results_dir = vt.results_dir
        if not vt.valid:
          safe_mkdir(results_dir, clean=True)
          resolver_for_target_type.resolve_target(self, vt.target, results_dir, node_paths)
        node_paths.resolved(vt.target, results_dir)
        build_graph.inject_dependency(
          dependent=vt.target.address,
          dependency=webpack_distribution_target.address,
        )

  def create_synthetic_target(self, global_fingerprint):
    """Return a synthetic target that represents the resolved webpack distribution."""
    spec_path = os.path.join(os.path.relpath(self.workdir, get_buildroot()))
    name = "webpack-distribution-{}".format(global_fingerprint)
    address = Address(spec_path=spec_path, target_name=name)
    logger.debug("Adding synthetic WebPackDistribution target: {}".format(name))
    new_target = self.context.add_new_target(
      address,
      WebPackDistribution,
      distribution_fingerprint=global_fingerprint
    )
    return new_target
